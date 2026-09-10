# Android App → API Playbook

Drop this file into a fresh Claude Code session started in your project folder.
It is a reusable procedure for any device or service that is only controllable
through an Android app: reverse the protocol the app uses, then build a small
authenticated wrapper API so your own clients can control it without the app.

The emulator is a discovery tool, not part of the running service.

## Fill in per project

- **APP / DEVICE:** <e.g. "smart cat feeder", "WiFi camera", "smart plug">
- **APP PACKAGE:** <e.g. co.vendor.app — find with `adb shell pm list packages`>
- **DESIRED ENDPOINTS:** <e.g. POST /feed, GET /status>
- **SERVER LANGUAGE:** <Node / Python / Go>
- **PHYSICAL/REAL-WORLD ACTION?** <yes/no — does an endpoint cause an
  irreversible physical effect? If yes, the feed-guard section is mandatory.>

## Architecture

```
client → HTTPS + API key → my server → vendor cloud / MQTT / local API → device
```

- The device is usually NOT reached on the local LAN. Most consumer IoT devices
  connect out to the vendor cloud; the app talks to that same cloud. My server
  calls that cloud on the client's behalf.
- Some devices DO expose a local API (ONVIF/RTSP for cameras, a local HTTP/JSON
  or MQTT endpoint). If so, the wrapper talks to the device directly — but the
  emulator NAT can block LAN discovery; a physical Android device on the same
  WiFi, driven over adb, is often easier for that case.
- My server is the single place that holds credentials, enforces auth + rate
  limiting, and absorbs vendor API changes. Clients never see vendor creds.

## Plan (in order)

1. **Install the official Android Emulator (AVD).**
   ```
   sdkmanager "platform-tools" "emulator" "system-images;android-34;google_apis;x86_64"
   avdmanager create avd -n rev -k "system-images;android-34;google_apis;x86_64"
   emulator -avd rev -gpu host
   ```
2. **Install the app** (`adb install <app>.apk`, or a Play image + Play Store if
   it needs Play Services) and sign in.
3. **Capture the protocol.** Run the app behind an HTTPS proxy (mitmproxy /
   Charles) with the proxy CA trusted, then perform each action you want to
   automate (e.g. the control action and the status screen). Save the requests.
4. **Identify the protocol** from the capture: base URL, auth (token? how
   obtained/refreshed?), each action request (+ params), and a status/read
   request. Note whether it is REST/JSON, MQTT, Tuya/SmartLife white-label, or a
   local device API.
5. **Build the server** — a small web service wrapping those calls. Build order:
   1. A **READ** endpoint first (e.g. status) — nothing changes while debugging.
   2. Then the **WRITE/action** endpoints, with the action-guard in place.
   3. Then add auth (per-client API key) and expose it.
6. **Retire the emulator** for daily use. Keep the AVD; do not delete it — it is
   needed again if the vendor API changes, a token needs re-capturing, or more
   endpoints are wanted.

## Server requirements

- Keep the endpoint set minimal — one per action plus a read.
- **Auth:** per-client API key/token. Write endpoints are NEVER unauthenticated.
- **Action-guard (only if an endpoint has a real-world effect):**
  - Rate limit (e.g. max N actions/hour).
  - Idempotency key so a retry does not repeat the action.
- Store vendor credentials server-side (env var / secrets file); refresh tokens
  if they expire.
- TLS in front. Host on a small VPS, or tunnel from home (Cloudflare Tunnel /
  Tailscale).

## Guardrails / known risks

- **Physical actions are irreversible.** If an endpoint dispenses food, unlocks
  a door, etc., retry loops or duplicated commands cause real harm. Rate limit +
  idempotency key are mandatory for those endpoints.
- **Cert pinning:** if the app pins its certificate hard, the proxy sees only
  encrypted bytes and step 3 fails. Many consumer apps do not pin; hardened ones
  (banking, social, dating) usually do. If it pins, the plan shifts to a
  rooted/debuggable image + a Frida-style unpin hook (more involved).
- **Integrity/attestation:** apps using Play Integrity (Instagram, Hinge, most
  major consumer apps) may refuse to run or log in on an emulator, especially a
  rooted one. Small IoT/utility apps rarely check. Know which class your app is.
- **Vendor dependency:** the wrapper rides an undocumented cloud on one account.
  They can rotate tokens, rate-limit, or change the API. Fine for a
  personal/family integration; not sound as a truly open public service.
- **Local-network devices:** the standard emulator's NAT often blocks
  mDNS/SSDP/broadcast device discovery. Use `adb reverse` for a known port, or a
  physical device on the real WiFi.
- **"Public" = people I gave a key**, not unauthenticated internet access.
- **Terms of service:** automating some apps violates their ToS. IoT/utility
  apps are generally fine; scraping other users' data or automating accounts on
  social/dating apps is not — do not build that.

## First actions for Claude Code

1. Confirm the OS, installed SDK/adb, and whether the emulator is set up.
2. Ask me to fill in the "Fill in per project" block if blank.
3. Walk me through the proxy capture (step 3) and ask me to paste the captured
   action + status requests.
4. Identify the protocol from what I paste, then scaffold the server starting
   with the READ endpoint.

## Worked example: smart cat feeder

- APP / DEVICE: automatic cat feeder. APP PACKAGE: <vendor package>.
- ENDPOINTS: `GET /status`, `POST /feed` (portion param).
- PHYSICAL ACTION: yes — `/feed` dispenses real food. Action-guard mandatory:
  rate limit + idempotency key.
- Likely protocol: vendor cloud REST/JSON or MQTT; possibly a Tuya/SmartLife
  white-label (documented API + open-source libs exist if so).
- Build `GET /status` first; wire `POST /feed` only after the read path works.
