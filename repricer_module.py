"""
BeyBay 自動調價模組
====================
先在 Supabase SQL Editor 執行以下 SQL：

CREATE TABLE repricer_settings (
  id              bigint generated always as identity primary key,
  user_id         uuid references auth.users(id) on delete cascade,
  item_id         text not null,
  item_title      text,
  min_price       numeric(10,2) not null,
  max_price       numeric(10,2) not null,
  strategy        text default 'second_lowest',
  -- 策略選項：lowest / second_lowest / top3
  auto_execute    boolean default false,
  notify_telegram boolean default false,
  telegram_token  text,
  telegram_chat_id text,
  is_active       boolean default true,
  last_checked    timestamptz,
  last_action     text,
  created_at      timestamptz default now()
);

alter table repricer_settings enable row level security;
create policy "select_own" on repricer_settings for select using (auth.uid() = user_id);
create policy "insert_own" on repricer_settings for insert with check (auth.uid() = user_id);
create policy "update_own" on repricer_settings for update using (auth.uid() = user_id);
create policy "delete_own" on repricer_settings for delete using (auth.uid() = user_id);

CREATE TABLE repricer_log (
  id           bigint generated always as identity primary key,
  user_id      uuid references auth.users(id) on delete cascade,
  item_id      text,
  item_title   text,
  old_price    numeric(10,2),
  new_price    numeric(10,2),
  competitor_price numeric(10,2),
  action       text,
  -- 'adjusted' / 'skipped_min_price' / 'already_competitive' / 'pending_approval'
  executed     boolean default false,
  created_at   timestamptz default now()
);

alter table repricer_log enable row level security;
create policy "select_own_log" on repricer_log for select using (auth.uid() = user_id);
create policy "insert_own_log" on repricer_log for insert with check (auth.uid() = user_id);
create policy "update_own_log" on repricer_log for update using (auth.uid() = user_id);
"""

import streamlit as st
import requests
import xml.etree.ElementTree as ET
from datetime import datetime


# ─────────────────────────────────────────────
# Supabase 操作
# ─────────────────────────────────────────────

def get_repricer_settings(user_id: str) -> list:
    """讀取用戶的所有調價規則"""
    try:
        admin = st.session_state._supabase_admin
        res = admin.table("repricer_settings") \
            .select("*") \
            .eq("user_id", user_id) \
            .execute()
        return res.data or []
    except Exception as e:
        return []


def save_repricer_setting(user_id: str, setting: dict) -> bool:
    """新增或更新調價規則"""
    try:
        admin = st.session_state._supabase_admin
        existing = admin.table("repricer_settings") \
            .select("id") \
            .eq("user_id", user_id) \
            .eq("item_id", setting["item_id"]) \
            .execute()

        if existing.data:
            admin.table("repricer_settings") \
                .update(setting) \
                .eq("user_id", user_id) \
                .eq("item_id", setting["item_id"]) \
                .execute()
        else:
            setting["user_id"] = user_id
            admin.table("repricer_settings").insert(setting).execute()
        return True
    except Exception as e:
        st.error(f"儲存失敗：{e}")
        return False


def delete_repricer_setting(user_id: str, item_id: str):
    """刪除調價規則"""
    try:
        admin = st.session_state._supabase_admin
        admin.table("repricer_settings") \
            .delete() \
            .eq("user_id", user_id) \
            .eq("item_id", item_id) \
            .execute()
    except Exception as e:
        st.error(f"刪除失敗：{e}")


def save_repricer_log(user_id: str, log: dict):
    """記錄調價歷史"""
    try:
        admin = st.session_state._supabase_admin
        log["user_id"] = user_id
        admin.table("repricer_log").insert(log).execute()
    except Exception:
        pass


def get_repricer_log(user_id: str, limit: int = 20) -> list:
    """讀取調價歷史"""
    try:
        admin = st.session_state._supabase_admin
        res = admin.table("repricer_log") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        return res.data or []
    except Exception:
        return []


def execute_log_item(user_id: str, log_id: int):
    """標記某條調價記錄為已執行"""
    try:
        admin = st.session_state._supabase_admin
        admin.table("repricer_log") \
            .update({"executed": True}) \
            .eq("id", log_id) \
            .eq("user_id", user_id) \
            .execute()
    except Exception as e:
        st.error(f"更新失敗：{e}")


# ─────────────────────────────────────────────
# eBay Browse API — 搜尋競爭對手價格
# ─────────────────────────────────────────────

def get_competitor_prices(title: str, your_item_id: str, token: str, ep: dict) -> list:
    """
    用 Browse API 搜尋同款產品，回傳排序後的競爭對手價格列表
    """
    # 取標題前 50 字作搜尋關鍵字
    keywords = title[:50].strip()

    try:
        res = requests.get(
            f"{ep['api']}/buy/browse/v1/item_summary/search",
            headers={
                "Authorization":    f"Bearer {token}",
                "Content-Type":     "application/json",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_GB",
            },
            params={
                "q":      keywords,
                "limit":  "20",
                "filter": "buyingOptions:{FIXED_PRICE}",
                "sort":   "price",
            },
            timeout=15,
        )
        data = res.json()
        items = data.get("itemSummaries", [])

        prices = []
        for item in items:
            iid   = item.get("itemId", "")
            price = item.get("price", {})
            val   = float(price.get("value", 0))
            cur   = price.get("currency", "GBP")
            ititle = item.get("title", "")

            # 排除自己的刊登
            if your_item_id and your_item_id in iid:
                continue
            if val > 0:
                prices.append({
                    "item_id": iid,
                    "title":   ititle,
                    "price":   val,
                    "currency": cur,
                    "url":     item.get("itemWebUrl", ""),
                })

        # 按價格排序
        prices.sort(key=lambda x: x["price"])
        return prices

    except Exception as e:
        return []


def calculate_target_price(
    competitor_prices: list,
    your_price: float,
    min_price: float,
    max_price: float,
    strategy: str,
) -> tuple:
    """
    根據策略計算目標售價
    回傳 (target_price, competitor_ref_price, action_reason)
    """
    if not competitor_prices:
        return your_price, None, "no_competitors"

    lowest       = competitor_prices[0]["price"]
    second_lowest = competitor_prices[1]["price"] if len(competitor_prices) > 1 else lowest
    top3_avg     = sum(p["price"] for p in competitor_prices[:3]) / min(3, len(competitor_prices))

    # 選擇參考價
    if strategy == "lowest":
        ref_price = lowest - 0.01
        ref_label = "最低價"
    elif strategy == "second_lowest":
        ref_price = second_lowest - 0.01
        ref_label = "第二低價"
    else:  # top3
        ref_price = round(top3_avg - 0.01, 2)
        ref_label = "前三平均"

    # 套用底線保護
    target = round(max(min_price, min(ref_price, max_price)), 2)

    if target < min_price:
        return your_price, ref_price, f"skipped_min_price（{ref_label} £{ref_price:.2f} 低於底線 £{min_price:.2f}）"
    if abs(target - your_price) < 0.01:
        return your_price, ref_price, "already_competitive"

    return target, ref_price, f"adjusted（{ref_label} £{ref_price:.2f}）"


# ─────────────────────────────────────────────
# Trading API — 更新售價
# ─────────────────────────────────────────────

def update_item_price(item_id: str, new_price: float, token: str, ep: dict) -> bool:
    """用 Trading API ReviseItem 更新售價"""
    trading_url = "https://api.ebay.com/ws/api.dll" \
        if "sandbox" not in ep["api"] \
        else "https://api.sandbox.ebay.com/ws/api.dll"

    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{token}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <StartPrice currencyID="GBP">{new_price:.2f}</StartPrice>
  </Item>
  <ErrorLanguage>en_US</ErrorLanguage>
</ReviseItemRequest>"""

    try:
        res = requests.post(
            trading_url,
            headers={
                "X-EBAY-API-SITEID":              "3",
                "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
                "X-EBAY-API-CALL-NAME":           "ReviseItem",
                "Content-Type":                   "text/xml",
            },
            data=xml_body.encode("utf-8"),
            timeout=15,
        )
        root = ET.fromstring(res.text)
        ns   = {"e": "urn:ebay:apis:eBLBaseComponents"}
        ack  = root.findtext("e:Ack", namespaces=ns)
        return ack in ["Success", "Warning"]
    except Exception:
        return False


# ─────────────────────────────────────────────
# Telegram 通知
# ─────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, message: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────
# 主調價掃描函數
# ─────────────────────────────────────────────

def run_repricer_scan(user_id: str, listings: list, get_token_fn, ep: dict) -> list:
    """
    掃描所有啟用的調價規則，回傳建議列表
    """
    settings = get_repricer_settings(user_id)
    if not settings:
        return []

    token = get_token_fn()
    if not token:
        return []

    results = []
    setting_map = {s["item_id"]: s for s in settings if s["is_active"]}

    for item in listings:
        item_id = item.get("item_id", "")
        if item_id not in setting_map:
            continue

        s          = setting_map[item_id]
        your_price = float(item.get("price") or 0)
        title      = item.get("title", "")

        # 搜尋競爭對手
        competitors = get_competitor_prices(title, item_id, token, ep)

        # 計算目標價格
        target, ref_price, action = calculate_target_price(
            competitors,
            your_price,
            float(s["min_price"]),
            float(s["max_price"]),
            s["strategy"],
        )

        result = {
            "item_id":        item_id,
            "title":          title,
            "your_price":     your_price,
            "target_price":   target,
            "ref_price":      ref_price,
            "action":         action,
            "competitors":    competitors[:5],
            "auto_execute":   s["auto_execute"],
            "notify_telegram":s["notify_telegram"],
            "telegram_token": s.get("telegram_token", ""),
            "telegram_chat_id": s.get("telegram_chat_id", ""),
            "setting":        s,
        }

        # 自動執行
        if s["auto_execute"] and "adjusted" in action and abs(target - your_price) >= 0.01:
            success = update_item_price(item_id, target, token, ep)
            result["executed"] = success
            log_action = "adjusted" if success else "failed"

            save_repricer_log(user_id, {
                "item_id":         item_id,
                "item_title":      title,
                "old_price":       your_price,
                "new_price":       target,
                "competitor_price": ref_price,
                "action":          log_action,
                "executed":        success,
            })

            if success and s["notify_telegram"] and s.get("telegram_token"):
                send_telegram(
                    s["telegram_token"],
                    s["telegram_chat_id"],
                    f"🏷️ <b>BeyBay 自動調價</b>\n"
                    f"產品：{title[:50]}\n"
                    f"舊價：£{your_price:.2f} → 新價：£{target:.2f}\n"
                    f"競爭對手：£{ref_price:.2f}",
                )
        else:
            result["executed"] = False
            if "adjusted" in action:
                save_repricer_log(user_id, {
                    "item_id":         item_id,
                    "item_title":      title,
                    "old_price":       your_price,
                    "new_price":       target,
                    "competitor_price": ref_price,
                    "action":          "pending_approval",
                    "executed":        False,
                })

        results.append(result)

    return results


# ─────────────────────────────────────────────
# UI：自動調價 Tab
# ─────────────────────────────────────────────

def render_repricer_tab(user_id: str, listings: list, get_token_fn, ep: dict):
    """渲染自動調價 Tab"""

    st.markdown("### 🏷️ 自動調價設定")

    # ── 子頁面切換 ──
    sub = st.radio(
        "功能",
        ["📋 調價規則", "▶️ 立即掃描", "📜 調價記錄"],
        horizontal=True,
        label_visibility="collapsed",
    )

    # ════════════════════════════════
    # 子頁一：調價規則設定
    # ════════════════════════════════
    if sub == "📋 調價規則":
        settings = get_repricer_settings(user_id)
        setting_ids = {s["item_id"] for s in settings}

        st.markdown("#### 為產品設定調價規則")

        if not listings:
            st.info("請先到「刊登管理」tab 刷新列表，載入你的 eBay 刊登。")
            return

        # 選擇產品
        listing_options = {
            f"{item.get('title', '')[:50]} (£{item.get('price', 'N/A')})": item
            for item in listings
        }
        selected_label = st.selectbox("選擇要設定的產品", list(listing_options.keys()))
        selected_item  = listing_options[selected_label]
        item_id        = selected_item.get("item_id", "")
        current_price  = float(selected_item.get("price") or 0)

        # 載入已有規則
        existing = next((s for s in settings if s["item_id"] == item_id), {})

        st.divider()
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**價格範圍**")
            min_price = st.number_input(
                "最低售價 £（成本保護）",
                min_value=0.01,
                value=float(existing.get("min_price", current_price * 0.8)),
                step=0.50,
                help="調價不會低於此價格",
            )
            max_price = st.number_input(
                "最高售價 £",
                min_value=0.01,
                value=float(existing.get("max_price", current_price * 1.2)),
                step=0.50,
                help="調價不會高於此價格",
            )

            strategy = st.selectbox(
                "調價策略",
                ["second_lowest", "lowest", "top3"],
                index=["second_lowest", "lowest", "top3"].index(
                    existing.get("strategy", "second_lowest")
                ),
                format_func=lambda x: {
                    "lowest":       "跟最低價（激進）",
                    "second_lowest":"跟第二低價（穩健）",
                    "top3":         "跟前三平均（保守）",
                }[x],
            )

        with col2:
            st.markdown("**執行設定**")
            auto_execute = st.toggle(
                "全自動執行（無需確認）",
                value=existing.get("auto_execute", False),
                help="開啟後系統自動更新 eBay 售價，關閉則只顯示建議",
            )
            notify_telegram = st.toggle(
                "Telegram 通知",
                value=existing.get("notify_telegram", False),
            )

            telegram_token   = ""
            telegram_chat_id = ""
            if notify_telegram:
                telegram_token = st.text_input(
                    "Telegram Bot Token",
                    value=existing.get("telegram_token", ""),
                    type="password",
                )
                telegram_chat_id = st.text_input(
                    "Telegram Chat ID",
                    value=existing.get("telegram_chat_id", ""),
                )

            is_active = st.toggle(
                "啟用此規則",
                value=existing.get("is_active", True),
            )

        # 儲存
        col_save, col_del = st.columns([3, 1])
        with col_save:
            if st.button("💾 儲存規則", type="primary", use_container_width=True):
                if min_price >= max_price:
                    st.error("最低售價必須低於最高售價")
                else:
                    ok = save_repricer_setting(user_id, {
                        "item_id":          item_id,
                        "item_title":       selected_item.get("title", ""),
                        "min_price":        min_price,
                        "max_price":        max_price,
                        "strategy":         strategy,
                        "auto_execute":     auto_execute,
                        "notify_telegram":  notify_telegram,
                        "telegram_token":   telegram_token,
                        "telegram_chat_id": telegram_chat_id,
                        "is_active":        is_active,
                    })
                    if ok:
                        st.success(f"✅ 規則已儲存：{selected_item.get('title', '')[:40]}")
                        st.rerun()

        with col_del:
            if item_id in setting_ids:
                if st.button("🗑️ 刪除規則", use_container_width=True):
                    delete_repricer_setting(user_id, item_id)
                    st.success("已刪除")
                    st.rerun()

        # 顯示所有已設定的規則
        if settings:
            st.divider()
            st.markdown(f"#### 已設定規則（{len(settings)} 條）")
            for s in settings:
                status = "✅ 啟用" if s["is_active"] else "⏸ 暫停"
                auto   = "🤖 全自動" if s["auto_execute"] else "👁 人工確認"
                tg     = "📱 Telegram" if s["notify_telegram"] else ""
                strategy_label = {
                    "lowest": "跟最低價",
                    "second_lowest": "跟第二低價",
                    "top3": "跟前三平均",
                }.get(s["strategy"], s["strategy"])

                with st.expander(f"{status} {s.get('item_title', s['item_id'])[:45]}"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("最低售價", f"£{s['min_price']:.2f}")
                    c2.metric("最高售價", f"£{s['max_price']:.2f}")
                    c3.metric("策略", strategy_label)
                    st.caption(f"{auto} {tg}")

    # ════════════════════════════════
    # 子頁二：立即掃描
    # ════════════════════════════════
    elif sub == "▶️ 立即掃描":
        settings = get_repricer_settings(user_id)
        active   = [s for s in settings if s["is_active"]]

        if not active:
            st.info("尚未設定任何調價規則，請先到「📋 調價規則」tab 設定。")
            return

        if not listings:
            st.info("請先到「刊登管理」tab 刷新列表。")
            return

        st.markdown(f"**{len(active)} 條規則待掃描**")

        if st.button("🔍 立即掃描競爭對手價格", type="primary", use_container_width=True):
            with st.spinner("掃描中，正在搜尋競爭對手價格..."):
                results = run_repricer_scan(user_id, listings, get_token_fn, ep)
            st.session_state.repricer_results = results

        # 顯示掃描結果
        results = st.session_state.get("repricer_results", [])
        if results:
            st.divider()
            for r in results:
                action     = r["action"]
                your_price = r["your_price"]
                target     = r["target_price"]
                ref        = r["ref_price"]
                title      = r["title"]
                executed   = r.get("executed", False)

                # 狀態顏色
                if "adjusted" in action and not executed:
                    icon = "🟡"  # 待確認
                elif executed:
                    icon = "🟢"  # 已執行
                elif "skipped" in action:
                    icon = "🔴"  # 低於底線
                else:
                    icon = "⚪"  # 無需調整

                with st.expander(f"{icon} {title[:55]}"):
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric("你的現價", f"£{your_price:.2f}")
                    col_b.metric("競爭對手", f"£{ref:.2f}" if ref else "N/A")
                    col_c.metric(
                        "建議售價",
                        f"£{target:.2f}",
                        delta=f"{target - your_price:+.2f}" if target != your_price else None,
                    )

                    st.caption(f"動作：{action}")

                    # 競爭對手列表
                    if r["competitors"]:
                        st.markdown("**競爭對手（最低5個）：**")
                        for i, c in enumerate(r["competitors"], 1):
                            st.write(f"{i}. £{c['price']:.2f} — {c['title'][:40]}")

                    # 人工確認執行按鈕
                    if "adjusted" in action and not executed and not r["auto_execute"]:
                        if st.button(
                            f"✅ 確認調價至 £{target:.2f}",
                            key=f"exec_{r['item_id']}",
                            type="primary",
                        ):
                            token = get_token_fn()
                            if token:
                                success = update_item_price(r["item_id"], target, token, ep)
                                if success:
                                    # 更新 log
                                    logs = get_repricer_log(user_id, 50)
                                    pending = next(
                                        (l for l in logs
                                         if l["item_id"] == r["item_id"]
                                         and not l["executed"]), None
                                    )
                                    if pending:
                                        execute_log_item(user_id, pending["id"])

                                    # Telegram
                                    s = r["setting"]
                                    if s.get("notify_telegram") and s.get("telegram_token"):
                                        send_telegram(
                                            s["telegram_token"],
                                            s["telegram_chat_id"],
                                            f"🏷️ <b>BeyBay 調價確認</b>\n"
                                            f"產品：{title[:50]}\n"
                                            f"£{your_price:.2f} → £{target:.2f}",
                                        )
                                    st.success(f"✅ 已更新售價至 £{target:.2f}")
                                    st.session_state.repricer_results = []
                                    st.rerun()
                                else:
                                    st.error("❌ 更新失敗，請稍後再試")

                    elif executed:
                        st.success("✅ 已自動執行")
                    elif "skipped" in action:
                        st.warning("⚠️ 低於底線，已跳過")
                    elif "already_competitive" in action:
                        st.info("✅ 你的價格已具競爭力，無需調整")

    # ════════════════════════════════
    # 子頁三：調價記錄
    # ════════════════════════════════
    elif sub == "📜 調價記錄":
        logs = get_repricer_log(user_id, 30)

        if not logs:
            st.info("尚無調價記錄，請先執行掃描。")
            return

        st.markdown(f"**最近 {len(logs)} 條記錄**")

        for log in logs:
            old_p  = log.get("old_price", 0)
            new_p  = log.get("new_price", 0)
            comp_p = log.get("competitor_price", 0)
            action = log.get("action", "")
            exec_  = log.get("executed", False)
            ts     = log.get("created_at", "")[:16].replace("T", " ")

            icon = "✅" if exec_ else ("⏳" if "pending" in action else "⏭️")

            with st.expander(f"{icon} {log.get('item_title', '')[:50]} — {ts}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("原售價",   f"£{old_p:.2f}")
                c2.metric("競爭對手", f"£{comp_p:.2f}" if comp_p else "N/A")
                c3.metric("建議/新價", f"£{new_p:.2f}",
                          delta=f"{new_p - old_p:+.2f}" if new_p != old_p else None)
                st.caption(f"動作：{action} | 已執行：{'是' if exec_ else '否'}")
