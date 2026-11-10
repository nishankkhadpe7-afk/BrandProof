# BrandProof for Figma

Checks the text in your selected frames or text layers against your workspace's brand rules and approved facts, without leaving Figma.

## Install (development plugin, about 1 minute)
1. Open the **Figma desktop app** (web Figma can't load local plugins).
2. Menu → **Plugins → Development → Import plugin from manifest…** and pick `figma-plugin/manifest.json`.
3. Run it from **Plugins → Development → BrandProof**.

## Use
1. Enter your API address (e.g. `https://<your-backend>.onrender.com`, or `http://localhost:8000` locally) and, optionally, the web app address for links.
2. Sign in with your BrandProof account or a demo account, then pick the brand workspace.
3. Select frames or text layers and click **Check selection**.
4. Each finding names the layer. **Show layer** zooms to it, and **Apply fix** replaces the text in place, keeping its styling.
5. Tick **Also send to the review queue** to create a submission (with a PNG of the frame) for a reviewer to approve in the web app.

Only text is sent to your server, plus the frame image if you choose to send it to the review queue. The sign-in token is kept in Figma's plugin storage on your machine.

## Publishing to the Figma Community (later)
Replace `"id"` in `manifest.json` with the ID Figma gives you, and narrow `allowedDomains` to your API address.
