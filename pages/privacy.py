import streamlit as st

st.set_page_config(
    page_title="Privacy Policy - BeyBay",
    page_icon="🔒",
    layout="centered"
)

st.title("🔒 Privacy Policy")
st.caption("Last updated: April 2026")

st.divider()

st.markdown("""
## 1. Introduction

BeyBay ("we", "our", "us") is an independent eBay seller management platform
that helps eBay sellers manage their product listings, inventory, and pricing.
This Privacy Policy explains what data we collect, how we use it, and your rights.

This platform is **not affiliated with, endorsed by, or officially connected to eBay Inc.**

---

## 2. Data We Collect

When you connect your eBay account to BeyBay, we collect and store:

| Data | Purpose |
|------|---------|
| eBay Access Token (encrypted) | To manage listings on your behalf |
| eBay Refresh Token (encrypted) | To maintain your session without re-login |
| eBay Seller ID | To identify your account |
| Product listing data | To display and manage your inventory |

---

## 3. What We Do NOT Collect

We will **never** collect:

- Your eBay password — authentication is handled entirely by eBay's official servers
- Payment or banking information
- Personal messages or buyer communications
- Any data beyond what is necessary to provide the service

---

## 4. How We Use Your Data

Your data is used solely to:

- Connect to eBay API on your behalf
- Display your current listings and inventory
- Apply changes you instruct us to make (pricing, stock levels, descriptions)
- Automatically refresh your session token to maintain uninterrupted access

We do **not** sell, share, or rent your data to any third party.

---

## 5. Data Security

All eBay tokens are protected using **AES-256 encryption (Fernet)** before storage.
Encryption keys are stored separately from the encrypted data.
Even in the unlikely event of a data breach, your tokens cannot be read without the
encryption key.

---

## 6. Data Retention

Your data is retained for as long as your account is active on BeyBay.
If you disconnect your eBay account or delete your BeyBay account, all associated
tokens and data are permanently deleted within 30 days.

---

## 7. Revoking Access

You can revoke BeyBay's access to your eBay account at any time without contacting us:

1. Log in to your eBay account
2. Go to **My eBay → Account → Sign in and security**
3. Select **Third-party app access**
4. Find **BeyBay** and click **Remove**

Once revoked, all tokens become immediately invalid and we can no longer access your account.

---

## 8. Your Rights

Under UK GDPR and applicable data protection law, you have the right to:

- **Access** the personal data we hold about you
- **Correct** inaccurate data
- **Delete** your data (right to erasure)
- **Restrict** how we process your data
- **Object** to our processing of your data

To exercise any of these rights, please contact us using the details below.

---

## 9. Cookies

BeyBay does not use tracking cookies or advertising cookies.
Streamlit may use essential session cookies to maintain your login state.

---

## 10. Changes to This Policy

We may update this Privacy Policy from time to time. Any changes will be posted
on this page with an updated date. Continued use of BeyBay after changes constitutes
acceptance of the updated policy.

---

## 11. Contact Us

For any privacy-related questions or requests:

**BeyBay Support**
Email: support@beybay.streamlit.app
Website: https://beybay.streamlit.app

---

*This privacy policy was last reviewed in April 2026.*
""")

st.divider()
st.caption("© 2026 BeyBay. All rights reserved. Not affiliated with eBay Inc.")
