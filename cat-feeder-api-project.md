# Cat Feeder API — Project Brief

Drop this file into a fresh Claude Code session started in your project folder
(e.g. `C:\Users\<you>\cat-feeder-api\`). It defines the goal, the plan, and the
guardrails.

## Goal

The cat feeder is only controllable through its Android app. Reverse the
protocol the app uses, then build a small authenticated server (a wrapper API)
that lets my own clients trigger feeds and read status without the app. The
emulator is a discovery tool, not part of the running service.

## Architecture

```
client → HTTPS + API key → my server → vendor cloud / MQTT → feeder
```

- The feeder is NOT reached on the local LAN. It almost certainly connects out
  to the vendor cloud; the app talks to that same cloud. My server calls that
  cloud on the client's behalf.
- My server is the single place that holds the vendor credentials, enforces
  auth + rate limiting, and absorbs vendor API changes.
- Clients never see vendor credentials.

## Plan (in order)

1. **Install the official Android Emulator (AVD)** from the Android SDK
   command-line tools. Use a Google APIs x86_64 image, Android 34.
   ```
   sdkmanager "platform-tools" "emulator" "system-images;android-34;google_apis;x86_64"
   avdmanager create avd -n feeder -k "system-images;android-34;google_apis;x86_64"
   emulator -avd feeder -gpu host
   ```
2. **Install the feeder app** on the emulator (`adb install <app>.apk`, or via
   the Play image + Play Store if the app needs Play Services), and sign in.
3. **Capture the protocol.** Run the app behind an HTTPS proxy (mitmproxy /
   Charles) with the proxy CA trusted, then perform a feed and open the status
   screen. Save the captured requests.
4. **Identify the protocol** from the capture: base URL, auth (token? how it is
   obtained/refreshed?), the `feed`/`dispense` request (+ portion param), and a
   `status` request. Note whether it is REST/JSON, MQTT, or Tuya/SmartLife
   white-label.
5. **Build the server** — a small web service wrapping those calls. Build order:
   1. `GET /status` first (a READ — no food moves while debugging).
   2. Then `POST /feed` with the feed-guard in place.
   3. Then add auth (per-client API key) and expose it.
6. **Retire the emulator** for daily use. Keep the AVD; do not delete it — it is
   needed again if the vendor API changes, a token needs re-capturing, or more
   endpoints are wanted.

## Server requirements

- Endpoints: `POST /feed` (portion + API key), `GET /status`. Keep it minimal.
- **Auth:** per-client API key/token. `/feed` is NEVER unauthenticated.
- **Feed-guard (protects the actual cat):**
  - Rate limit (e.g. max N feeds/hour).
  - Idempotency key so a retry does not double-dispense.
- Store the vendor token server-side (env var / secrets file); refresh it if it
  expires.
- TLS in front. Host on a small VPS, or tunnel from home (Cloudflare Tunnel /
  Tailscale).
- Language: <FILL IN — Node / Python / Go>.

## Guardrails / known risks

- **Physical action:** every `/feed` dispenses real food to a real cat. Retry
  loops, misreads, or duplicated commands over-feed. The rate limit +
  idempotency key are not optional.
- **Cert pinning:** if the app pins its certificate hard, the proxy sees only
  encrypted bytes and step 3 fails. Consumer feeder apps often do not pin. If it
  does pin, the plan shifts to a rooted/debuggable image + a Frida-style unpin
  hook (more involved) — decide then.
- **Vendor dependency:** the wrapper rides the vendor's undocumented cloud on
  one account. They can rotate tokens, rate-limit, or change the API. Fine for a
  personal/family integration; not sound as a truly open public service.
- **"Public" = people I gave a key**, not unauthenticated internet access.

## First actions for Claude Code

1. Confirm the OS, installed SDK/adb, and whether the emulator is already set up.
2. Walk me through the proxy capture (step 3) and ask me to paste the captured
   `feed` and `status` requests.
3. Identify the protocol from what I paste, then scaffold the server starting
   with `GET /status`.
