# GPT-Register-Tool

A Windows-oriented tool for ChatGPT account registration, email OTP handling, account management, protocol-based payment link extraction, and explicit payment execution.

The project uses a **WPF desktop application + Python business core** architecture. The desktop application provides operation entry points, configuration, and result visualization, while the Python modules handle email, registration, sessions, payments, proxies, and external service protocols. Runtime data is stored locally by default and is not committed to Git.

## Project Overview

### Main Workflow

```text
Email Source
  -> ChatGPT Email OTP Registration
  -> Obtain Access Token / Session, using a stable HTTP 200 AT as the persistence boundary
  -> Optional Phone Verification and Codex OAuth
  -> JIT AT Probe/Refresh and Optional Protocol Payment Link Extraction
  -> Session JSON + SQLite Index
  -> Unified Management through the WPF Desktop Application
```

### Use Cases

* Perform bulk email-based registration using an email pool, ReMail, or CFWorker.
* Centrally poll OTPs from Microsoft, Gmail, iCloud verification links, ReMail, CFWorker, and other mailbox providers.
* Manage local accounts, sessions, quota status, and payment links.
* Select proxy egress by stage and extract PayPal or other local payment method links.
* Export account data to formats compatible with Codex, CPA, SUB2API, and other targets.

### Technology Stack

| Layer              | Technologies                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------------- |
| Desktop            | WPF, .NET 10, C#, Generic Host, CommunityToolkit.Mvvm, WPF-UI                                                       |
| Business Core      | Python 3, curl_cffi, requests, httpx, PyNaCl (Ed25519)                                                              |
| Data Storage       | JSON, JSONL, SQLite                                                                                                 |
| Email Protocols    | ReMail API, CFWorker, iCloud verification links, Microsoft Graph/OAuth, IMAP, Gmail IMAP                            |
| Payment Protocols  | Stripe Checkout, PayPal, GoPay, GCash, GrabPay, UPI, iDEAL, PIX, Kakao Pay, BLIK, TWINT, Direct Card Checkout, MoMo |
| Browser Assistance | Playwright, Camoufox, CloakBrowser                                                                                  |

## Installation and Deployment

### Requirements

* Windows 10/11 x64.
* Python 3.10 or later.
* `curl_cffi==0.16.0`. The registration preflight check validates both the installed version and the `chrome146` profile. Older versions will not proceed to mailbox purchasing or registration.
* .NET 10 Desktop Runtime; the .NET 10 SDK is required when building from source.
* **Node.js 18+** (`node` must be available in PATH): the Sentinel Token QuickJS extractor uses `node` to execute OpenAI's actual `sdk.js`. If Node.js is missing, OTPs may be silently dropped during registration.
* **Playwright Chromium**: Stripe initialization for protocol payments such as MoMo and Direct Card uses the Chromium network stack for TLS. Install it with `python -m playwright install chromium`.
* A network environment capable of reaching the target mailbox providers, ChatGPT, and payment services.
* Registration proxies, mailbox receiving proxies, and protocol payment proxies are independent. Mailbox receiving uses `http://127.0.0.1:7897` by default.

After installing the dependencies, run the environment preflight check to verify that Node.js, Playwright Chromium, and critical Python packages are available:

```powershell
python scripts/preflight_env.py
```

### Option 1: Installer

Download the latest installer from GitHub Releases:

```text
GPT-Register-Tool-Setup-vYYYY.MM.DD.exe
```

Run the installer and select an installation directory. Before the first launch, install the Python dependencies and create the local configuration:

```powershell
python -m pip install -r requirements.txt
copy config.example.json config.json
```

### Option 2: Portable ZIP

Download and extract:

```text
GPT-Register-Tool-win-x64-vYYYY.MM.DD.zip
```

Run the following commands from the extracted directory:

```powershell
python -m pip install -r requirements.txt
copy config.example.json config.json
.\dist\net10\SmsWorkbench.exe
```

### Option 3: Run from Source

```powershell
git clone https://github.com/2951461586/GPT-Register-Tool.git
cd GPT-Register-Tool
python -m pip install -r requirements.txt
copy config.example.json config.json
powershell -ExecutionPolicy Bypass -File .\SmsWorkbench\build_dotnet.ps1
.\dist\net10\SmsWorkbench.exe
```

The desktop application must be built using `SmsWorkbench/build_dotnet.ps1`. Do not run `dotnet build` directly, because it only produces intermediate files and does not update the standard `dist/net10` workspace.

### Initial Configuration

Open the **Settings** page in the desktop application and configure at least the following:

1. Under **Network & Payments**, configure the registration proxy pool, mailbox receiving proxy, and protocol payment proxy pool separately.
2. Under **Email & Receiving**, configure ReMail, CFWorker, or another mailbox source.
3. Configure SMSBower, CPA, SUB2API, and protocol payment parameters as needed.
4. Save the configuration and reopen the relevant feature to apply the new settings.

The ReMail API Key can also be provided through an environment variable:

```powershell
$env:REMAIL_API_KEY = "rk-your-key"
```

Environment variables take precedence over `config.json`. API Keys saved through the desktop Settings page are written only to the local, Git-ignored `config.json`.

### UPI payment-link CLI (no registration)

`paylink` is a standalone extractor. It does not register accounts, poll mailboxes, or launch the WPF app. Give it an existing ChatGPT access token (or a session JSON that already contains one) and it runs the UPI checkout → Stripe confirm → approve → poll path.

```powershell
python -m paylink --token "ACCESS_TOKEN" --proxy "http://127.0.0.1:7897"
python -m paylink --session .\sessions\session_example.json
python -m paylink --sessions-dir .\sessions --workers 4
```

Each line of stdout is one JSON result. A `upi://` deep link is preferred; otherwise a hosted checkout URL is returned.

## Key Features

### One-Click Registration

* Supports registration using email pools, short-lived ReMail verification mailboxes, CFWorker domain mailboxes, and SMSBower phone numbers.
* Supports both single-account and concurrent bulk registration.
* Each registration account independently extracts its Sentinel Token and `oai-did`; authentication transactions are never reused across accounts. `_extract_sentinel` allows two concurrent extraction tasks by default through `sentinel_max_concurrency`, with a maximum of four, balancing batch throughput against Sentinel rate-limit risk.
* The registration flow is responsible only for account authentication and AT/Session persistence. It no longer generates payment links.
* Registration success is determined by an AT probe returning HTTP 200. Candidates that do not continuously return HTTP 200 during the stability probe window are not added to the active account database.
* The registration flow no longer executes the Agent Identity stage. Agent Identity must be handled through the explicit SUB2API import path when required.
* When an email record is selected, registration prioritizes the selected email. If no email is selected, an email source selector is displayed.
* Registration, OTP, Session acquisition, and Codex OAuth results are recorded separately by stage to prevent intermediate states from being incorrectly reported as successful. Payment link extraction is triggered only through an independent payment operation.

### Protocol Consistency and Recovery

* Before claiming or purchasing a mailbox, the CLI sequentially performs network preflight checks against ChatGPT, Auth, and Sentinel, then selects the first available route from the registration proxy pool. Mailboxes are not consumed when TLS, proxy, or profile requirements are not satisfied.
* Each account is bound to an independent proxy session. During bulk registration, proxies are switched and new sessions are created only when network or authentication failures occur; a single transaction is not split across different egress routes.
* NextAuth, Auth API, and ChatGPT use their own Header templates while sharing stable `oai-did`, `oai-session-id`, call ID, UA, and client hints.
* Fingerprint language and timezone are generated according to proxy GeoIP. Sentinel QuickJS uses the same UA, platform, timezone, screen, memory, and client hints.
* Sentinel separately generates `username_password_create`, `authorize_continue`, and `oauth_create_account` tokens. If the DID values in the Token, Cookie, and Header do not match, the process terminates with `sentinel_extract_failed`.
* A circuit breaker is opened after a session receives HTTP 403/429. No additional requests are made during the cooldown period. Production registration does not allow a plain HTTP PoW fallback.
* After account creation and AT acquisition, the candidate and checkpoint are persisted immediately before running the HTTP 200 AT liveness probe. Proxy/TLS liveness failures can resume from the checkpoint without repeating the email OTP or account creation stages.

### ReMail Email Source

* The one-click registration source includes `ReMail Persistent Mailbox`, which consistently uses the `purchase` persistent mailbox mode.
* Supports both single and bulk mailbox order creation.
* For batches of approximately 100 accounts, the default HTTP timeout scales by two seconds per mailbox, with a minimum of 30 seconds. This can be overridden using `email_registration.remail.batch_timeout`.
* Supports `private_first` and `public_only` inventory strategies.
* Supports selecting specific projects, products, and email suffixes.
* Uses `Idempotency-Key` to prevent retries from creating duplicate orders.
* Order creation uses the API Key, while receiving mail uses the mailbox address and a separate Service Token.
* If a Service Token returns HTTP 401, the API Key is used to query the associated order. If the server returns a new Token, it is saved to the Session JSON and SQLite database before retrying once.
* `code` orders can receive messages only before `receiveUntil`. The API Key cannot replace an expired Service Token. Use `purchase` when continued inbox access is required.
* If an email summary does not contain a verification code, the full message is automatically retrieved and filtered by timestamp, recipient, message ID, and previously excluded verification codes.
* When ReMail returns a structured six-digit verification code from a trusted OpenAI sender, the exact recipient and timestamp are validated. This avoids unnecessary timeouts even when localized subjects are garbled.
* The desktop application can open the inbox from a ReMail registration record. View mode retrieves the complete message body and verification code.
* API Keys and Service Tokens are redacted in logs.
* Adaptive OTP polling uses an initial 1-second delay with progressive backoff (`1s → 1.5s → 3s`). The polling interval is dynamically adjusted according to message arrival status and server rate-limit recommendations, reducing unnecessary requests.
* ReMail receiving allows a default server clock skew of 90 seconds. Message ID snapshots still prevent old verification codes from being reused.
* If ReMail has not received the verification code within 30 seconds, one resend is triggered. During the remaining time, the latest verification code belonging to the current transaction is accepted.
* Existing ReMail orders can be restored from an email Token file using `remail://email---serviceToken---orderNo---purchaseId`, without purchasing them again.
* If a bulk purchase encounters a timeout or retryable 5xx response, the system first strictly matches new orders by request time window, project, product, and quantity. Automatic recovery occurs only when exactly one matching order is found, preventing duplicate purchases after a lost response.
* `ReMail Persistent Mailbox` continues purchasing until the requested number of stable HTTP 200 ATs is reached. The desktop application uses a default purchasing limit and automatically manages registration batches. SMSBower phone verification is enabled by default in this mode. The CLI can still impose additional limits through `--max-mailbox-purchases` and `--max-remail-cost`.

### Unified Email and OTP Handling

The unified mailbox seam supports:

* ReMail.
* CFWorker domain mailboxes.
* Microsoft Graph/OAuth.
* Outlook/Hotmail IMAP fallback.
* Gmail IMAP and SMTP.
* iCloud verification links. Both the desktop application's "Import Email" feature and the backend support `email----verificationURL` and `email---verificationURL`.
* Chatai, token files, and historical email pool formats.

OTP parsing supports subject matching, sender filtering, exact recipient matching, server timestamp filtering, and candidate sorting.

### Protocol Payment Link Extraction

* Supports PayPal, GoPay, GCash, GrabPay, UPI, iDEAL, PIX, Kakao Pay, BLIK, TWINT, Direct Card Checkout, and MoMo.

* BLIK submits a one-time six-digit code and directly executes the payment. It is available only in the single-account protocol payment dialog/command and is not included in post-registration automatic link extraction or the bulk payment selector.

* Direct Card Checkout (Philippines, PH/PHP): performs US order creation → TR promotion refresh → zero-amount validation, producing a long direct card checkout URL in the form `chatgpt.com/checkout/<entity>/<cs_id>`.

* MoMo (Vietnam, VN/VND): order creation → Stripe init → enforce ₫0 → create MoMo PM → Confirm → Approve → follow redirect, producing a scannable `payment.momo.vn` QR code. The QR code is automatically decoded to PNG for use with "Open QR Code."

* GoPay (Indonesia, ID/IDR), GCash, and GrabPay (Philippines, PH/PHP) reuse the same wallet adapter: Checkout → Stripe init → create wallet PM → Confirm → Approve → Poll → validate Provider Redirect. They differ only by region, currency, locale, and final-domain allowlist.

* PayPal supports Hosted long URLs, direct PP links, and forced zero-cost trial mode.

* PayPal return reconciliation is handled independently by `paypal_reconciliation.py`. It follows only allowlisted Stripe Return → OpenAI Pay → Checkout Verify transitions and outputs redacted `conclusive` / `unknown` / `failed` evidence. It does not modify the link extraction interface or generate/overwrite payment links.

* Supports segmented `checkout`, `approve`, and `update` proxies.

* Dynamic proxies automatically rewrite the target country and Session according to the payment method, supporting US, JP, VN, ID, IN, NL, BR, KR, PL, CH, PH, and other egress regions.

* The protocol payment proxy pool is probed sequentially. If the current proxy is unavailable or its egress country does not match the requested country, the next proxy is selected automatically.

* Region and proxy selections are stored in history.

* Supports actual testing of proxy egress IP, country, and expected-region matching.

* Strictly distinguishes Checkout, PM creation, Confirm, initial Poll, and final Provider Redirect stages.

* Generic link extraction terminal states are `completed`, `failed`, `cancelled`, `unknown`, and `timed_out`. Every result includes `retryable` and `error_stage`. `unknown` additionally sets `requires_reconciliation=true`, preventing automatic retries until reconciliation is completed. `cancelled` is not retried, while ordinary `timed_out` results can be retried according to policy.

* Before running bulk link extraction, the local quota endpoint should be used to filter out HTTP 401 accounts. Reports must separately count AT availability, plan/trial eligibility, payment method visibility, successful Approve operations, and final link/QR artifacts.

* MoMo is considered successful only when it returns `ready_with_qr` and produces either a `payment.momo.vn` URL or QR code file. `account_trial_ineligible`, `card_only_full_price`, and `approve_result_blocked` are explicit failure states.

* The bulk payment executor supports JIT AT, layered HTTP 401 recovery (RT, Cookie, isolated-browser email OTP, Codex OAuth), eligibility probing, Canary pausing, per-method concurrency, transient retries, atomic checkpoints, and same-batch resume.

* MoMo uses stage-specific proxies for Checkout, Promotion, Stripe Provider, Approve, and Redirect. Kakao produces structured results and considers link extraction successful only when an explicit Kakao/Nicepay Redirect is obtained.

### Agent Identity and SUB2API Import Boundary

* The Agent Identity/task stage has been removed from the primary registration flow. Agent Identity failures do not affect HTTP 200 AT registration results.
* Existing Agent Identity JSON can still be consumed by the explicit SUB2API import path. Creating or rebuilding an Agent Identity can only be triggered through that import flow.
* Agent Identity uses an Ed25519 PKCS#8 private key stored separately under `sessions/agent_identities/`. Private keys are never written to logs.
* `--register-and-import` can be used to automatically import into SUB2API after registration.
* SUB2API import supports three credential modes: `auto`, `oauth`, and `agent_identity`. These modes affect only the import boundary and do not reinsert Agent Identity into the registration stage.
* The SUB2API export format is compatible with the Go backend. The `expires_at` field uses a Unix timestamp (`int64`).
* `--sub2api-no-verify` can be used to skip post-import connectivity verification.

### Account and Data Management

* Dual-layer indexing using Session JSON and SQLite.
* Centralized display of account status, AT state (obtained/not obtained/HTTP 401 invalid), RT, payment links, and phone verification results.
* The left-side **Account Liveness Check** performs AT/quota health checks. HTTP 401 accounts are recovered through RT, Cookie, isolated-browser email OTP, and Codex OAuth, in that order, during explicit recovery or payment JIT flows.
* Supports copying ATs, viewing mailboxes, re-registering, and regenerating payment links.
* Supports Codex JSON, CPA, SUB2API, and other import/export workflows.
* Account records retain registration region, registration batch, and persistence status, making it easier to select bulk-payment accounts by cohort.
* Local data is stored under `sessions/` and `runtime/` by default. Both directories are ignored by Git.

### Desktop Bulk Payment Operations

1. Select the accounts to process from the account list, then open **Bulk Protocol Payment** from the left sidebar or the context menu.
2. Select a link extraction method such as MoMo, Kakao, or Direct Card Checkout, and configure concurrency, transient retries, Canary count, batch ID, and proxy Seed.
3. **Automatic 401 Recovery** is enabled by default. When **Eligibility Probe Only** is selected, the process completes JIT AT, registration-region matrix evaluation, ChatGPT Checkout, and Stripe init, then stops before PM creation, Confirm, Approve, and Provider Redirect. Results explicitly record amount, currency, payment method visibility, and `eligible` / `ineligible` / `unknown` classification.
4. Use the **Account Region / Payment Eligibility Matrix** to verify the registration, Checkout, Promotion, Provider, Approve, and Redirect region combination.
5. Reusing the same batch ID with the same mode, matrix, proxy, and retry parameters loads the atomic checkpoint from `runtime/payment_batches/` and resumes execution. If runtime parameters change, the signature no longer matches and the batch is executed again. Probe results are not reused for actual payment execution. Systematic `unknown` Canary results pause subsequent full batches for that method. Explicitly unavailable payment methods or non-zero quotes are not incorrectly classified as protocol failures. Reports separately display AT 200, JIT refresh, capability probe, eligibility, link, QR code, and failure counts.

### Phone Verification

* Supports SMSBower country and price-tier queries.
* Supports configurable send retries, wait timeouts, and polling intervals.
* Supports Codex OAuth phone verification and account refresh workflows.
* Bulk operations preserve email-to-phone result mappings, making single-account failures easier to troubleshoot.

## Project Architecture

### Layered Structure

```text
SmsWorkbench/
  WPF Desktop Application
  -> Generic Host / DI Composition Root
  -> Progressive MVVM pages, configuration, lists, task launching, status display

IBackendClient
  -> ArgumentList + cancellation/timeout/process-tree termination
  -> @@SMSWORKBENCH_IPC_V1@@ single-line versioned result envelope

sms_tool/cli.py
  CLI and task orchestration
  -> Argument parsing, batch tasks, process exit status

sms_tool/registration.py
  Primary registration flow
  -> Email OTP, account creation, Session, Codex OAuth

sms_tool/registration_concurrency.py
  Registration-stage resource gating
  -> Network, AT probe, and payment-stage concurrency limits and wait metrics

sms_tool/account_liveness.py / account_recovery.py
  Account liveness and recovery
  -> Side-effect-free quota probing, explicit OAuth recovery, and state persistence

sms_tool/payment_auth.py / payment_batch.py
  JIT AT gate and bulk protocol payments
  -> Layered 401 recovery, Checkout/Stripe capability probing, eligibility matrix,
     Canary, retries, checkpoint reports

sms_tool/checkout_contract.py / payment_capability.py
  Unified Checkout contract and payment-method capability probing
  -> Region/currency/locale, Stripe init, amount, and payment-method catalog normalization

sms_tool/wallet_provider.py / wallet_transport.py
  Shared wallet adapter for GoPay, GCash, and GrabPay
  -> PM, Confirm, Approve, Poll, Provider Redirect, and stage-specific proxies

sms_tool/mailbox.py
  Unified mailbox routing
  -> ReMail / CFWorker / Graph / IMAP / Gmail

sms_tool/payment_link_manager.py
  Protocol payment manager
  -> Method registration, segmented proxies, five terminal states,
     unified retryable/error_stage results

sms_tool/paypal_reconciliation.py
  Independent PayPal return reconciliation
  -> Allowlisted redirect state machine, secret redaction,
     conclusive/unknown classification

sms_tool/storage.py
  Data persistence
  -> Session JSON, SQLite, state, and deduplication

services/
  Optional local protocol services
  -> Mail diagnostics, additional payment extractors
```

### Core Modules

| Module                                 | Responsibility                                                                                       |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `SmsWorkbench/`                        | WPF desktop UI, Settings page, task entry points, and local status display                           |
| `sms_tool/cli.py`                      | CLI arguments and high-level task orchestration                                                      |
| `sms_tool/registration.py`             | ChatGPT registration, OTP, Session, and subsequent verification                                      |
| `sms_tool/registration_concurrency.py` | Registration-stage resource groups, concurrency gating, and wait metrics                             |
| `sms_tool/account_liveness.py`         | `/backend-api/wham/usage` liveness probing, response classification, and quota parsing               |
| `sms_tool/account_recovery.py`         | Local quota refresh, layered 401 recovery, candidate AT validation, and disabled-account persistence |
| `sms_tool/mailbox.py`                  | Mailbox provider routing and unified OTP polling                                                     |
| `sms_tool/mailbox_remail.py`           | ReMail ordering, receiving, message detail retrieval, and OTP extraction                             |
| `sms_tool/mailbox_cfworker.py`         | CFWorker mailbox creation and receiving                                                              |
| `sms_tool/mailbox_graph.py`            | Microsoft OAuth and Graph boundary                                                                   |
| `sms_tool/mailbox_gmail.py`            | Gmail IMAP/SMTP and OAuth                                                                            |
| `sms_tool/mailbox_icloud_url.py`       | iCloud verification-link receiving, HTML/API body parsing, and OTP normalization                     |
| `sms_tool/payment_link_manager.py`     | Payment method registration, state machine, and unified results                                      |
| `sms_tool/checkout_contract.py`        | ChatGPT Checkout, Stripe init request/response, and payment-method capability evidence contract      |
| `sms_tool/payment_capability.py`       | Generic capability probing limited to Checkout + Stripe init                                         |
| `sms_tool/wallet_provider.py`          | Shared GoPay, GCash, and GrabPay orchestration and structured results                                |
| `sms_tool/wallet_transport.py`         | Wallet HTTP transport, stage-specific proxies, and Provider Redirect validation                      |
| `sms_tool/gen_pp_link.py`              | PayPal/Stripe Checkout and link generation                                                           |
| `sms_tool/paypal_proxy.py`             | Segmented proxies, region rotation, and egress probing                                               |
| `sms_tool/paypal_reconciliation.py`    | PayPal merchant-return reconciliation and redacted evidence, independent from link extraction        |
| `sms_tool/storage.py`                  | SQLite, Session indexing, and state persistence                                                      |
| `sms_tool/agent_identity.py`           | Explicit SUB2API Agent Identity credential conversion, Ed25519 key generation, and persistence       |
| `sms_tool/sub2api_import.py`           | SUB2API import with multiple authentication modes                                                    |
| `sms_tool/session_converter.py`        | Multi-format account and Session conversion                                                          |
| `sms_tool/payment_auth.py`             | Pre-payment AT probing, layered 401 recovery, and security telemetry                                 |
| `sms_tool/payment_batch.py`            | Bulk protocol payments, eligibility matrix, Canary, retries, and atomic checkpoints                  |
| `sms_tool/registration_progress.py`    | Registration-stage progress tracking and persistence                                                 |
| `sms_tool/error_classification.py`     | Error classification and retry/report normalization                                                  |

For more detailed boundary definitions, see `docs/architecture.md`. For directory responsibilities, see `docs/directory-map.md`.

## Core Configuration

### ReMail

```json
{
  "email_registration": {
    "remail": {
      "enabled": true,
      "base_url": "https://remail.aishop6.com",
      "api_key": "",
      "project_id": 2,
      "product_id": 5,
      "service_mode": "purchase",
      "supply": "private_first",
      "email_suffix": "outlook.com",
      "otp_poll_interval": 1,
      "batch_timeout": 200
    },
    "sentinel_max_concurrency": 2,
    "remail_otp_issued_after_grace_seconds": 90,
    "remail_otp_resend_after_seconds": 30
  }
}
```

### Registration and Mailbox Proxies

```json
{
  "mailbox_proxy": "http://127.0.0.1:7897",
  "proxy": {
    "registration": "http://user:pass-JP-session-5m@gateway:port",
    "default": "http://user:pass-JP-session-5m@gateway:port",
    "pool": ["http://user:pass-JP-session-5m@gateway:port"]
  }
}
```

Registration traffic uses JP dynamic proxies (`proxy.registration` / `proxy.pool`). Workers refresh dynamic Sessions so concurrent workers use different egress IPs. Email OTP retrieval always uses the fixed `mailbox_proxy` (default: `http://127.0.0.1:7897`) and does not inherit the registration proxy. Payment traffic uses the independent `paypal.stage_proxies` / `protocol_payments.proxy_pool`.

These three proxy groups do not override one another. Their configuration can be viewed and modified under **Settings → Network & Payments** in the desktop application.

### Protocol Payment Proxy Pool

```json
{
  "protocol_payments": {
    "proxy_pool": [
      "http://user-region-JP-sid-session-t-5:pass@gateway-a:port",
      "http://user-region-JP-sid-session-t-10:pass@gateway-b:port"
    ]
  }
}
```

The protocol payment proxy pool is independent from the registration proxy pool. During link extraction, `region-XX` or the country and dynamic Session encoded in the password are rewritten according to the target payment region. The protocol pool is overridden only when `--proxy` or an explicit stage-specific proxy is supplied.

### JIT AT and Bulk Payments

```json
{
  "registration": {
    "at_stability_probe_count": 2,
    "at_stability_probe_delay_seconds": 10,
    "at_probe_timeout_seconds": 30,
    "stage_concurrency": { "network": 4, "at_probe": 4 }
  },
  "protocol_payments": {
    "batch": {
      "method_workers": { "momo": 2, "kakao": 2 },
      "pause_on_canary_failure": true,
      "canary_pause_seconds": 21600
    },
    "matrix": {
      "cells": [
        { "name": "vn_sticky", "payment_method": "momo", "registration_country": "VN", "checkout_country": "VN", "promotion_country": "VN", "provider_country": "VN", "approve_country": "VN", "redirect_country": "VN", "strategy": "custom_promo", "sample_size": 5 }
      ]
    }
  }
}
```

Payment accounts returning HTTP 401 are recovered in the following order: OAuth Refresh Token, existing Cookie `/api/auth/session`, isolated-browser email OTP, and Codex OAuth. A candidate AT is written to Session JSON and SQLite only after it has again passed an HTTP 200 probe.

Browser contexts are isolated by account and validate the logged-in email address. `account_deactivated` is classified as a permanent failure and does not trigger repeated login attempts.

### SUB2API Import

```json
{
  "sub2api": {
    "auth_mode": "auto",
    "verify_after_import": true
  }
}
```

Supported `auth_mode` values are `auto`, `oauth`, and `agent_identity`. Agent Identity is used only at the explicit SUB2API import boundary. `verify_after_import` controls whether connectivity verification is performed after import.

### Emergency Environment Variable Overrides

If OpenAI rotates the Stripe publishable key or Sentinel SDK version and this causes payment link extraction or registration OTP failures, environment variables can temporarily override the values without modifying the code:

* `PP_STRIPE_PUBLISHABLE_KEY`: globally overrides the fallback Stripe publishable key used by protocol payments. It is shared by `sms_tool/gen_pp_link.py` and `services/protocol-payment/momo/ac_paylink_core.py`. Checkout responses normally include this key, so the fallback is used only when the response omits it. A WARN log is emitted when the fallback is used.
* `OPENAI_SENTINEL_VERSION`: overrides the Sentinel SDK version. The default value is built into `sms_tool/sentinel_quickjs.py`. An HTTP 403/404 while downloading the SDK usually indicates that the current version has been rotated out. Update this variable or the `sentinel_version` configuration value.

Before launching, run `python scripts/preflight_env.py` to verify Node.js, Playwright Chromium, and critical Python packages.

## Common Operations

### ReMail Short-Lived Verification Registration (CLI Only)

```powershell
python chatgpt_phone_reg.py --remail-service-mode code --count 1 --workers 1 --registration-at-only --no-phone-reuse
```

### ReMail Persistent Mailbox Registration with SMSBower Phone Verification

```powershell
python chatgpt_phone_reg.py --buy-remail-mailbox --remail-service-mode purchase --target-at200 40 --max-mailbox-purchases 80 --workers 10 --phone-reuse --phone-source smsbower
```

### ReMail Persistent Mailbox AT-Only Protocol Registration

```powershell
python chatgpt_phone_reg.py --buy-remail-mailbox --remail-service-mode purchase --count 1 --workers 1 --registration-at-only --no-phone-reuse
```

This mode skips Codex OAuth RT and phone verification. Registration is counted as successful only after the Session has been persisted and the AT liveness probe returns HTTP 200.

### CFWorker Email Registration

```powershell
python chatgpt_phone_reg.py --buy-cfworker-mailbox --cfworker-domain example.com --count 1 --workers 1
```

### Register from an Email File

```powershell
python chatgpt_phone_reg.py --chatai-mailbox-file hotmail.txt --count 4 --workers 4
```

### Test Payment Proxy Egress

```powershell
python chatgpt_phone_reg.py --test-payment-proxies --checkout-proxy-country GB --approve-proxy-country JP --update-proxy-country BR
```

### Bulk Protocol Payments with Resume Support

```powershell
python chatgpt_phone_reg.py --extract-payment-link --payment-method momo --email-file runtime\eligible.txt --workers 2 --payment-batch-id momo_vn_20260731 --payment-canary 5 --payment-retries 1
```

### Direct Card Checkout Link Extraction

Extract a PH/PHP zero-amount Checkout URL:

```powershell
python chatgpt_phone_reg.py --extract-payment-link --payment-method direct_card --email user@example.com --proxy "http://proxy"
```

Run a single-account GoPay Canary that performs JIT AT, the ID matrix, Checkout, and Stripe init capability probing without creating a payment method or sending Confirm/Approve:

```powershell
python chatgpt_phone_reg.py --extract-payment-link --payment-method gopay --email-file runtime\canary.txt --payment-probe-only --payment-canary 1 --payment-batch-id gopay_id_probe --workers 1
```

### Register and Automatically Import into SUB2API

```powershell
python chatgpt_phone_reg.py --buy-remail-mailbox --count 1 --workers 1 --register-and-import --sub2api-auth-mode auto
```

### View CLI Arguments

```powershell
python chatgpt_phone_reg.py --help
```

## Testing, Building, and Releasing

### Run Tests

```powershell
python -m pytest -q
python -m compileall -q sms_tool
.\.dotnet\dotnet.exe test .\GPTRegisterTool.slnx -c Release
```

`global.json` pins the repository SDK, while `Directory.Packages.props` centrally manages NuGet package versions. The standard xUnit project is located at `tests/SmsWorkbench.Tests`. CI runs Python tests, C# tests, and the standard desktop publishing pipeline.

### Build the Desktop Application

```powershell
powershell -ExecutionPolicy Bypass -File .\SmsWorkbench\build_dotnet.ps1
```

Standard output directory:

```text
dist/net10/SmsWorkbench.exe
```

### Build the Installer and Portable Package

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1 -Version vYYYY.MM.DD
```

Release files are written to `dist/release/`:

* Windows graphical installer.
* Portable ZIP package.
* SHA-256 checksum file.

Internal signed builds can use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1 -Version vYYYY.MM.DD -SelfSign
```

### Release Checklist

1. Confirm that `config.json`, email credentials, proxy passwords, API Keys, and Tokens have not been committed to Git.
2. Run the complete test suite, sample configuration parsing, Python compilation checks, and `git diff --check`.
3. Update `dist/net10` using the only supported build script.
4. Build the installer, portable package, and checksum file, then verify the SHA-256 values in the checksum manifest.
5. Confirm that the release commit has been pushed and `git status --short` is empty. Ignored local data such as `runtime/` and `sessions/` must not be included in the release commit.
6. Create a version tag on that commit and upload the Release assets generated by the same build.
7. GitHub Release titles and descriptions should consistently use Chinese. Commands, filenames, and error codes should remain in their original format.

Current releases use `vYYYY.MM.DD`. Documentation or build revisions made on the same day use patch tags such as `vYYYY.MM.DD.1`.

The installer, portable ZIP, and SHA-256 file must all originate from the same `scripts/build_installer.ps1` build, and their hashes must be verified before upload.

Release asset names are fixed as:

```text
GPT-Register-Tool-Setup-<version>.exe
GPT-Register-Tool-win-x64-<version>.zip
GPT-Register-Tool-<version>.sha256.txt
```

## Data and Security

* `config.json`, `sessions/`, `runtime/`, email pools, and Token files are ignored by Git by default.
* Example configurations do not contain real API Keys, email credentials, or proxy passwords.
* ReMail API Keys and Service Tokens are redacted in exceptions and logs.
* Payment links, BA Tokens, account AT/RT values, and email credentials are sensitive data and should not be shared publicly.
* Availability and pricing for third-party email, payment, proxy, and SMS verification services are determined by their respective providers.

## Documentation

* [Architecture](docs/architecture.md)
* [Directory Responsibilities](docs/directory-map.md)
* [PayPal Zero-Due Link Guide](docs/paypal-zero-due-link.md)
* [Latest Release Notes](docs/release-v2026.08.09.md)
* [Proxy Guide](PROXY_GUIDE.md)

## License and Usage Responsibility

Use this project only in scenarios where you have proper authorization and where its use complies with applicable service terms, regional laws and regulations, and organizational policies.

Users are responsible for third-party service fees, account security, and data compliance.
