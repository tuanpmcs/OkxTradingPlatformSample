# Lovable Prompt For Pulse Desk UI

Create a polished trading desktop UI called "Pulse Desk" for an Electron app.

Requirements:
- Build a responsive single-page interface with a premium, warm, modern aesthetic.
- Include controls: symbol input, channel select, URL input, connect button, simulate button, stop button.
- Include status display and cards for latest price, tick change, message rate, source.
- Include a large line chart section titled "Price Change Timeline".
- Use expressive typography and custom color variables.
- Avoid generic template look; make it bold and intentional.

Critical Electron integration contract:
- In renderer code, use `window.streamApi` methods:
  - `window.streamApi.start({ symbol, channel, url, simulated })`
  - `window.streamApi.stop()`
  - `window.streamApi.onStatus((payload) => {})`
  - `window.streamApi.onData((payload) => {})`
- `payload` from `onData`:
  - `ts` (number timestamp)
  - `price` (number)
  - `change` (number)
  - `source` (string)
- `payload` from `onStatus`:
  - `state` (idle|connecting|connected|warning|error|disconnected)
  - `detail` (string)

Output format:
- Provide static frontend files suitable for Electron local loading.
- Ensure `index.html` can run from local file path without dev server.
