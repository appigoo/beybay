"""
BeyBay - 多用戶 eBay SaaS 管理平台
=====================================
Streamlit Secrets 需要設定：
  EBAY_CLIENT_ID     = "BarrySze-beybayap-SBX-f8f86d25c-ed0dc7f8"
  EBAY_CLIENT_SECRET = "SBX-8f86d25ca516-15fb-40c2-9c63-2a2b"
  EBAY_REDIRECT_URI  = "Barry_Sze-BarrySze-beybay-oacmlu"
  ENCRYPTION_KEY     = "你的 Fernet Key"
  SUPABASE_URL       = "https://eftrfbouonumjkmzatrv.supabase.co"
  SUPABASE_ANON_KEY  = "eyJhbGc..."
  SUPABASE_SERVICE_KEY = "eyJhbGc..."  ← service_role key

安裝依賴：
  pip install streamlit requests cryptography supabase
"""

import streamlit as st
import requests
import base64
import time
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from urllib.parse import urlencode
from supabase import create_client, Client

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
def get_config():
    return {
        "client_id":      st.secrets["EBAY_CLIENT_ID"],
        "client_secret":  st.secrets["EBAY_CLIENT_SECRET"],
        "redirect_uri":   st.secrets["EBAY_REDIRECT_URI"],
        "enc_key":        st.secrets["ENCRYPTION_KEY"],
        "supabase_url":   st.secrets["SUPABASE_URL"],
        "supabase_anon":  st.secrets["SUPABASE_ANON_KEY"],
        "supabase_svc":   st.secrets["SUPABASE_SERVICE_KEY"],
    }

CFG = get_config()

# ─────────────────────────────────────────────
# 環境切換 ← 改這一行切換 sandbox/production
# ─────────────────────────────────────────────
EBAY_ENV = "sandbox"  # 改為 "production" 切換正式環境

EBAY_ENDPOINTS = {
    "sandbox": {
        "auth":  "https://auth.sandbox.ebay.com/oauth2/authorize",
        "token": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
        "api":   "https://api.sandbox.ebay.com",
    },
    "production": {
        "auth":  "https://auth.ebay.com/oauth2/authorize",
        "token": "https://api.ebay.com/identity/v1/oauth2/token",
        "api":   "https://api.ebay.com",
    },
}
EP = EBAY_ENDPOINTS[EBAY_ENV]

SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
])

# ─────────────────────────────────────────────
# Supabase 客戶端
# ─────────────────────────────────────────────
@st.cache_resource
def get_supabase() -> Client:
    """一般用戶操作（受 RLS 保護）"""
    return create_client(CFG["supabase_url"], CFG["supabase_anon"])

@st.cache_resource
def get_supabase_admin() -> Client:
    """管理員操作（繞過 RLS，存 Token 用）"""
    return create_client(CFG["supabase_url"], CFG["supabase_svc"])

# ─────────────────────────────────────────────
# 加密工具
# ─────────────────────────────────────────────
def encrypt(text: str) -> str:
    return Fernet(CFG["enc_key"].encode()).encrypt(text.encode()).decode()

def decrypt(encrypted: str) -> str:
    return Fernet(CFG["enc_key"].encode()).decrypt(encrypted.encode()).decode()

# ─────────────────────────────────────────────
# Session 初始化
# ─────────────────────────────────────────────
def init_session():
    defaults = {
        "supabase_session": None,   # Supabase 登入 session
        "user_id":          None,   # 當前用戶 UUID
        "user_email":       None,   # 當前用戶電郵
        "ebay_connected":   False,  # 是否已連接 eBay
        "access_token_enc": None,
        "refresh_token_enc":None,
        "token_expiry":     None,
        "listings":         [],
        "listings_raw":     {},
        "listings_status":  None,
        "auth_page":        "login", # login / register
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

# ─────────────────────────────────────────────
# Supabase 用戶認證
# ─────────────────────────────────────────────
def sign_up(email: str, password: str) -> dict:
    try:
        res = get_supabase().auth.sign_up({"email": email, "password": password})
        return {"success": True, "data": res}
    except Exception as e:
        return {"success": False, "error": str(e)}

def sign_in(email: str, password: str) -> dict:
    try:
        res = get_supabase().auth.sign_in_with_password({"email": email, "password": password})
        return {"success": True, "session": res.session, "user": res.user}
    except Exception as e:
        return {"success": False, "error": str(e)}

def sign_out():
    try:
        get_supabase().auth.sign_out()
    except Exception:
        pass
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ─────────────────────────────────────────────
# eBay Token 存取（Supabase）
# ─────────────────────────────────────────────
def save_ebay_token(user_id: str, access_token: str, refresh_token: str, expiry: datetime):
    """儲存加密 Token 到 Supabase"""
    admin = get_supabase_admin()
    # 先刪除舊的
    admin.table("ebay_accounts").delete().eq("user_id", user_id).execute()
    # 插入新的
    admin.table("ebay_accounts").insert({
        "user_id":        user_id,
        "access_token":   encrypt(access_token),
        "refresh_token":  encrypt(refresh_token),
        "token_expiry":   expiry.isoformat(),
        "ebay_client_id": CFG["client_id"],
    }).execute()

def load_ebay_token(user_id: str) -> dict | None:
    """從 Supabase 讀取 Token"""
    try:
        admin = get_supabase_admin()
        res = admin.table("ebay_accounts").select("*").eq("user_id", user_id).single().execute()
        return res.data
    except Exception:
        return None

def delete_ebay_token(user_id: str):
    """撤銷 eBay 授權"""
    get_supabase_admin().table("ebay_accounts").delete().eq("user_id", user_id).execute()

# ─────────────────────────────────────────────
# eBay OAuth
# ─────────────────────────────────────────────
def get_auth_url() -> str:
    params = {
        "client_id":     CFG["client_id"],
        "redirect_uri":  CFG["redirect_uri"],
        "response_type": "code",
        "scope":         SCOPES,
        "prompt":        "login",
    }
    return f"{EP['auth']}?{urlencode(params)}"

def exchange_code(code: str) -> dict:
    credentials = base64.b64encode(
        f"{CFG['client_id']}:{CFG['client_secret']}".encode()
    ).decode()
    res = requests.post(
        EP["token"],
        headers={
            "Content-Type":  "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
        data={
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": CFG["redirect_uri"],
        },
        timeout=15,
    )
    return res.json()

def refresh_token_fn(refresh_token: str) -> dict:
    credentials = base64.b64encode(
        f"{CFG['client_id']}:{CFG['client_secret']}".encode()
    ).decode()
    res = requests.post(
        EP["token"],
        headers={
            "Content-Type":  "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    return res.json()

def get_valid_token() -> str | None:
    """取得有效 Token，自動刷新"""
    if not st.session_state.access_token_enc:
        return None

    from datetime import timezone

    # 檢查是否快到期
    if st.session_state.token_expiry:
        expiry = datetime.fromisoformat(st.session_state.token_expiry) \
            if isinstance(st.session_state.token_expiry, str) \
            else st.session_state.token_expiry

        # 統一時區處理
        now = datetime.now(timezone.utc) if expiry.tzinfo else datetime.now()

        if now >= expiry:
            # 自動刷新
            refresh_tok = decrypt(st.session_state.refresh_token_enc)
            result = refresh_token_fn(refresh_tok)
            if "access_token" in result:
                new_expiry = datetime.now() + timedelta(seconds=result["expires_in"] - 60)
                st.session_state.access_token_enc = encrypt(result["access_token"])
                st.session_state.token_expiry = new_expiry
                # 同步更新 Supabase
                save_ebay_token(
                    st.session_state.user_id,
                    result["access_token"],
                    decrypt(st.session_state.refresh_token_enc),
                    new_expiry,
                )
            else:
                st.session_state.ebay_connected = False
                return None

    return decrypt(st.session_state.access_token_enc)

# ─────────────────────────────────────────────
# eBay API
# ─────────────────────────────────────────────
def ebay_get(endpoint: str) -> tuple:
    token = get_valid_token()
    if not token:
        return {"error": "未授權"}, 401
    res = requests.get(
        f"{EP['api']}{endpoint}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=15,
    )
    try:
        return res.json(), res.status_code
    except Exception:
        return {"raw": res.text}, res.status_code

def ebay_put(endpoint: str, body: dict) -> tuple:
    token = get_valid_token()
    if not token:
        return {"error": "未授權"}, 401
    res = requests.put(
        f"{EP['api']}{endpoint}",
        headers={
            "Authorization":    f"Bearer {token}",
            "Content-Type":     "application/json",
            "Content-Language": "en-US",
        },
        json=body,
        timeout=15,
    )
    try:
        data = res.json() if res.content else {}
    except Exception:
        data = {"raw": res.text}
    return data, res.status_code

def get_my_listings() -> tuple:
    """
    讀取真實刊登 — 用 Trading API（GetMyeBaySelling）
    這是大部分 eBay 賣家使用的舊系統，能讀到網站直接刊登的產品
    """
    token = get_valid_token()
    if not token:
        return [], {"error": "未授權"}, 401

    # Trading API 用 XML + POST
    trading_url = "https://api.ebay.com/ws/api.dll" \
        if EBAY_ENV == "production" \
        else "https://api.sandbox.ebay.com/ws/api.dll"

    xml_body = """<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{token}</eBayAuthToken>
  </RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination>
      <EntriesPerPage>50</EntriesPerPage>
      <PageNumber>1</PageNumber>
    </Pagination>
  </ActiveList>
  <SoldList>
    <Include>true</Include>
    <Pagination>
      <EntriesPerPage>10</EntriesPerPage>
    </Pagination>
  </SoldList>
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
</GetMyeBaySellingRequest>""".format(token=token)

    try:
        res = requests.post(
            trading_url,
            headers={
                "X-EBAY-API-SITEID":        "3",  # 3 = UK
                "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
                "X-EBAY-API-CALL-NAME":     "GetMyeBaySelling",
                "X-EBAY-API-APP-NAME":      CFG["client_id"],
                "Content-Type":             "text/xml",
            },
            data=xml_body.encode("utf-8"),
            timeout=20,
        )

        # 解析 XML 回應
        import xml.etree.ElementTree as ET
        ns = {"e": "urn:ebay:apis:eBLBaseComponents"}
        root = ET.fromstring(res.text)

        # 檢查是否成功
        ack = root.findtext("e:Ack", namespaces=ns)
        if ack not in ["Success", "Warning"]:
            errors = root.findall(".//e:Errors", namespaces=ns)
            error_msgs = [e.findtext("e:ShortMessage", namespaces=ns) for e in errors]
            return [], {"ack": ack, "errors": error_msgs, "raw": res.text[:500]}, 400

        # 提取 Active 刊登
        items = []
        active_list = root.find(".//e:ActiveList/e:ItemArray", namespaces=ns)
        if active_list:
            for item in active_list.findall("e:Item", namespaces=ns):
                items.append({
                    "item_id":       item.findtext("e:ItemID", namespaces=ns),
                    "title":         item.findtext("e:Title", namespaces=ns),
                    "price":         item.findtext("e:BuyItNowPrice", namespaces=ns)
                                     or item.findtext(".//e:StartPrice", namespaces=ns),
                    "currency":      "GBP",
                    "quantity":      item.findtext("e:QuantityAvailable", namespaces=ns, default="0"),
                    "watch_count":   item.findtext("e:WatchCount", namespaces=ns, default="0"),
                    "view_count":    item.findtext("e:HitCount", namespaces=ns, default="0"),
                    "time_left":     item.findtext("e:TimeLeft", namespaces=ns),
                    "listing_url":   item.findtext("e:ListingDetails/e:ViewItemURL", namespaces=ns),
                    "gallery_url":   item.findtext("e:PictureDetails/e:GalleryURL", namespaces=ns),
                    "condition":     item.findtext(".//e:ConditionDisplayName", namespaces=ns),
                    "source":        "trading_api",
                })

        raw_summary = {
            "ack":          ack,
            "total_active": root.findtext(".//e:ActiveList/e:PaginationResult/e:TotalNumberOfEntries", namespaces=ns),
            "total_sold":   root.findtext(".//e:SoldList/e:PaginationResult/e:TotalNumberOfEntries", namespaces=ns),
        }
        return items, raw_summary, 200

    except Exception as ex:
        return [], {"error": str(ex)}, 500

def create_inventory_item(sku, title, description, price, quantity) -> tuple:
    body = {
        "availability": {"shipToLocationAvailability": {"quantity": quantity}},
        "condition": "NEW",
        "product": {
            "title": title,
            "description": description,
            "aspects": {"Brand": ["Unbranded"]},
        },
    }
    return ebay_put(f"/sell/inventory/v1/inventory_item/{sku}", body)

# ─────────────────────────────────────────────
# OAuth Callback 處理
# ─────────────────────────────────────────────
def handle_oauth_callback():
    code = st.query_params.get("code")
    if code and st.session_state.user_id and not st.session_state.ebay_connected:
        with st.spinner("⏳ 向 eBay 換取授權 Token..."):
            result = exchange_code(code)

        if "access_token" in result:
            expiry = datetime.now() + timedelta(seconds=result.get("expires_in", 7200) - 60)

            # 存入 session
            st.session_state.access_token_enc  = encrypt(result["access_token"])
            st.session_state.refresh_token_enc = encrypt(result.get("refresh_token", ""))
            st.session_state.token_expiry      = expiry
            st.session_state.ebay_connected    = True

            # 存入 Supabase
            save_ebay_token(
                st.session_state.user_id,
                result["access_token"],
                result.get("refresh_token", ""),
                expiry,
            )

            st.query_params.clear()
            st.success("🎉 eBay 帳號授權成功！")
            time.sleep(1)
            st.rerun()
        else:
            st.error(f"授權失敗：{result.get('error_description', '未知錯誤')}")
            st.query_params.clear()

# ─────────────────────────────────────────────
# UI：登入 / 註冊頁
# ─────────────────────────────────────────────
def page_auth():
    st.markdown("""
    <div style="max-width:420px;margin:4rem auto;text-align:center">
        <h1 style="font-size:2.5rem">🛒 BeyBay</h1>
        <p style="color:#666">eBay 多帳號管理平台</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab_login, tab_register = st.tabs(["登入", "註冊"])

        with tab_login:
            email    = st.text_input("電郵", key="login_email", placeholder="you@example.com")
            password = st.text_input("密碼", key="login_password", type="password")

            if st.button("登入", type="primary", use_container_width=True):
                if email and password:
                    with st.spinner("登入中..."):
                        result = sign_in(email, password)
                    if result["success"]:
                        user = result["user"]
                        session = result["session"]
                        st.session_state.user_id    = user.id
                        st.session_state.user_email = user.email
                        st.session_state.supabase_session = session

                        # 從 Supabase 載入已有的 eBay Token
                        token_data = load_ebay_token(user.id)
                        if token_data:
                            st.session_state.access_token_enc  = token_data["access_token"]
                            st.session_state.refresh_token_enc = token_data["refresh_token"]
                            st.session_state.token_expiry      = token_data["token_expiry"]
                            st.session_state.ebay_connected    = True

                        st.rerun()
                    else:
                        st.error(f"登入失敗：{result['error']}")
                else:
                    st.warning("請填寫電郵和密碼")

        with tab_register:
            reg_email    = st.text_input("電郵", key="reg_email", placeholder="you@example.com")
            reg_password = st.text_input("密碼（最少6位）", key="reg_password", type="password")
            reg_confirm  = st.text_input("確認密碼", key="reg_confirm", type="password")

            if st.button("建立帳號", type="primary", use_container_width=True):
                if reg_email and reg_password and reg_confirm:
                    if reg_password != reg_confirm:
                        st.error("兩次密碼不一致")
                    elif len(reg_password) < 6:
                        st.error("密碼至少需要 6 個字元")
                    else:
                        with st.spinner("建立帳號中..."):
                            result = sign_up(reg_email, reg_password)
                        if result["success"]:
                            st.success("✅ 帳號建立成功！請檢查電郵確認後登入。")
                        else:
                            st.error(f"註冊失敗：{result['error']}")
                else:
                    st.warning("請填寫所有欄位")

# ─────────────────────────────────────────────
# UI：主控制台
# ─────────────────────────────────────────────
def page_dashboard():
    # Header
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0064D2,#003087);padding:1.5rem 2rem;
                border-radius:12px;margin-bottom:1.5rem;display:flex;
                justify-content:space-between;align-items:center">
        <div>
            <h1 style="color:white;margin:0;font-size:1.8rem">🛒 BeyBay</h1>
            <p style="color:#a8c8f0;margin:0;font-size:0.9rem">eBay 多帳號管理平台</p>
        </div>
        <div style="color:#a8c8f0;font-size:0.85rem">👤 {st.session_state.user_email}</div>
    </div>
    """, unsafe_allow_html=True)

    # eBay 連接狀態
    if st.session_state.ebay_connected:
        expiry = st.session_state.token_expiry
        if expiry:
            if isinstance(expiry, str):
                expiry = datetime.fromisoformat(expiry)
            # 統一處理時區：如果 expiry 有時區就用 UTC now，否則用 naive now
            from datetime import timezone
            if expiry.tzinfo is not None:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()
            remaining = max(0, int((expiry - now).total_seconds() // 60))
            st.success(f"✅ eBay 已授權 | Token 剩餘 {remaining} 分鐘（到期自動刷新）")
    else:
        st.warning("⚠️ 尚未連接 eBay 帳號")
        st.link_button("🔗 授權 eBay 帳號", get_auth_url(), type="primary")
        st.info("點擊後會跳到 eBay 官方頁面授權，我們不會接觸你的 eBay 密碼。", icon="🔒")
        st.divider()

    if not st.session_state.ebay_connected:
        st.stop()

    # 注入 supabase admin 供 repricer 使用
    st.session_state._supabase_admin = get_supabase_admin()

    # 功能分頁
    tab1, tab2, tab3, tab4 = st.tabs(["📦 刊登管理", "🏷️ 自動調價", "➕ 新增產品", "⚙️ 設定"])

    with tab1:
        st.markdown("### 我的 eBay 刊登")
        if st.button("🔄 刷新列表", type="secondary"):
            with st.spinner("讀取 eBay 資料中..."):
                items, raw, status = get_my_listings()
                st.session_state.listings        = items
                st.session_state.listings_raw    = raw
                st.session_state.listings_status = status

        if st.session_state.listings_status is not None:
            status = st.session_state.listings_status
            raw    = st.session_state.listings_raw
            if status == 200 and st.session_state.listings:
                total = raw.get("total_active", len(st.session_state.listings))
                st.success(f"✅ 成功讀取 {total} 件 Active 刊登")
            elif status == 200 and not st.session_state.listings:
                st.warning("⚠️ 此 eBay 帳號目前沒有 Active 刊登產品。")
            elif status == 403:
                st.error("❌ 權限不足（403）— 請重新授權")
            elif status == 400:
                errs = raw.get("errors", [])
                st.error(f"❌ API 錯誤：{', '.join([e for e in errs if e])}")
            else:
                st.error(f"❌ 錯誤 {status}")

            with st.expander("🔍 原始 API 回應（debug）"):
                st.json(raw)

        for item in st.session_state.listings:
            title     = item.get("title", "無標題")
            item_id   = item.get("item_id", "")
            price     = item.get("price", "N/A")
            qty       = item.get("quantity", "0")
            watches   = item.get("watch_count", "0")
            views     = item.get("view_count", "0")
            time_left = item.get("time_left", "")
            url       = item.get("listing_url", "")
            img       = item.get("gallery_url", "")
            condition = item.get("condition", "N/A")

            # 格式化剩餘時間
            def fmt_time(t):
                if not t:
                    return "N/A"
                t = t.replace("P", "").replace("T", " ").replace("D", "天 ").replace("H", "時 ").replace("M", "分").replace("S", "")
                return t.strip()

            with st.expander(f"📦 {title[:60]}"):
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    if img:
                        st.image(img, width=120)
                    st.write(f"**標題：** {title}")
                    st.write(f"**Item ID：** {item_id}")
                    st.write(f"**狀態：** {condition}")
                    if url:
                        st.markdown(f"[🔗 在 eBay 查看]({url})")
                with col_b:
                    st.metric("售價", f"£{price}")
                    st.metric("庫存", f"{qty} 件")
                    st.metric("關注者", f"{watches} 人")
                    st.metric("瀏覽", f"{views} 次")
                    st.write(f"⏱ 剩餘：{fmt_time(time_left)}")

    with tab2:
        from repricer_module import render_repricer_tab
        render_repricer_tab(
            user_id=st.session_state.user_id,
            listings=st.session_state.listings,
            get_token_fn=get_valid_token,
            ep=EP,
        )

    with tab3:
        st.markdown("### 新增庫存品項")
        col1, col2 = st.columns(2)
        with col1:
            sku         = st.text_input("SKU（唯一識別碼）", placeholder="FORTUNE-RAMEN-001")
            title       = st.text_input("產品標題", placeholder="Japanese Ramen Bowl Set")
            price       = st.number_input("售價 (USD)", min_value=0.01, value=9.99, step=0.01)
        with col2:
            quantity    = st.number_input("庫存數量", min_value=1, value=10)
            description = st.text_area("產品描述", placeholder="詳細描述你的產品...", height=130)

        if st.button("📤 提交到 eBay 庫存", type="primary", use_container_width=True):
            if sku and title and description:
                with st.spinner("提交中..."):
                    result, status = create_inventory_item(sku, title, description, price, quantity)
                if status in [200, 201, 204]:
                    st.success(f"✅ 成功建立 SKU: {sku}（{status}）")
                    st.info("去「刊登管理」tab 點「刷新列表」查看")
                else:
                    st.error(f"❌ 錯誤（{status}）")
                    with st.expander("錯誤詳情"):
                        st.json(result)
            else:
                st.warning("請填寫 SKU、標題、描述")

    with tab4:
        st.markdown("### 帳號設定")

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**BeyBay 帳號**")
            st.write(f"電郵：{st.session_state.user_email}")
            if st.button("🚪 登出 BeyBay", use_container_width=True):
                sign_out()

        with col_b:
            st.markdown("**eBay 授權**")
            st.write("環境：🧪 Sandbox（測試）")
            if st.button("❌ 撤銷 eBay 授權", use_container_width=True, type="secondary"):
                delete_ebay_token(st.session_state.user_id)
                st.session_state.ebay_connected    = False
                st.session_state.access_token_enc  = None
                st.session_state.refresh_token_enc = None
                st.session_state.token_expiry      = None
                st.session_state.listings          = []
                st.rerun()

        st.divider()
        st.caption("🔒 所有 eBay Token 以 AES-256 加密存儲於 Supabase，不存儲 eBay 密碼。")

# ─────────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="BeyBay - eBay 管理平台",
        page_icon="🛒",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    init_session()

    # OAuth callback 優先處理
    handle_oauth_callback()

    # 路由
    if st.session_state.user_id:
        page_dashboard()
    else:
        page_auth()

if __name__ == "__main__":
    main()
