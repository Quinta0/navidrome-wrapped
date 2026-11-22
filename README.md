# navidrome-wrapped

Your own year-in-music recap, built from your **ListenBrainz** and/or **Last.fm** history and your **Navidrome** server. It's like Spotify Wrapped, but self-hosted.

![Five slides (intro, top artist, new artists, peak month, summary card) from three generated designs](docs/screenshots.webp)

*Each row shows the same demo data rendered with a different design seed.*

- Animated full-screen slides: minutes listened, top artists, songs, albums, genres, new artists you discovered, peak month and hour, listening streaks, and stats about your library
- Every slide plays a matching song from your own Navidrome library
- **Generated design, unique every time**: each run builds its own design from a random seed: a colour palette (always WCAG AA readable), typography from 40 bundled variable fonts, each set to a random point in its design space (weight, width, slant and custom axes such as 3D tilt, morph, bounce or optical softness) and with those axes animated, plus outline/extrude/echo/glow effects, generated entrance animations and easing curves, generated SVG decorations, and for every slide which component variant shows the data (odometer, ring, echo or ticker numbers; letter-by-letter, highlighter or marquee headlines; podium, tiles, cloud or ticker rankings; bar, dot, line, radial or heat charts) and how it's laid out
- **Generated summary card**: six layouts (year band, banner, poster, vinyl, polaroid, big type), thirteen frame patterns, stickers and dividers. "Save image" renders that exact card to a PNG, so what you see is what you share
- One Python file with no dependencies. The output is a static folder that works on its own (songs and covers are downloaded, so the page contains **no credentials** and you can share it safely)

## Self-host with Docker

```sh
curl -O https://raw.githubusercontent.com/Quinta0/navidrome-wrapped/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/Quinta0/navidrome-wrapped/main/.env.example
# fill in .env, then:
docker compose up -d
```

Open http://localhost:8080. The first build takes a while (it reads your whole listening history once for the new artists card). After that, a recap of each month is built on the 1st of the next month, and the full-year recap on January 1 (see `REFRESH`). Open the page to pick one.

Or run it without compose:

```sh
docker run -d -p 8080:8080 --env-file .env -v ./data:/data ghcr.io/quinta0/navidrome-wrapped
```

### Unraid

1. **Settings → Docker**: make sure Docker is enabled.
2. Open the **Docker** tab and click **Add Container** at the bottom. Leave **Template** empty.
3. Fill in:
   - **Name**: `navidrome-wrapped`
   - **Repository**: `ghcr.io/quinta0/navidrome-wrapped:latest`
   - **Network Type**: `Bridge`
4. Switch on **Advanced View** (top right). In **Extra Parameters**, enter `--user 99:100`. This makes the files in appdata belong to `nobody:users`, like the rest of your containers.
5. Click **Add another Path, Port, Variable, Label or Device** and add a path:
   - **Config Type** `Path`, **Container Path** `/data`, **Host Path** `/mnt/user/appdata/navidrome-wrapped`
6. Add a port:
   - **Config Type** `Port`, **Container Port** `8080`, **Host Port** any free port, for example `8085`
7. Add one **Variable** per setting from the [configuration table](#configuration). The **Key** is the variable name. For example:
   - `LB_USER` and/or `LASTFM_USER` + `LASTFM_KEY`
   - `ND_URL`: your Navidrome's LAN address, for example `http://192.168.1.10:4533`. If Navidrome runs on the same Unraid box, use the Unraid IP and Navidrome's host port.
   - `ND_USER`, `ND_PASS`: set **Password Mask** to `Yes` for the password.
8. Create the data folder with the right owner first. Otherwise Docker creates it as root and the container can't write to it. Open the Unraid **Terminal** (`>_` icon, top right) and run:
   ```sh
   mkdir -p /mnt/user/appdata/navidrome-wrapped && chown 99:100 /mnt/user/appdata/navidrome-wrapped
   ```
9. Click **Apply**.
10. Click the container icon and choose **Logs**. The first build can take several minutes. It's done when you see `listens -> /data/site/index.html`.
11. Open `http://<unraid-ip>:8085`.

### TrueNAS SCALE (24.10 or later)

1. **Create a dataset.** Go to **Datasets**, select your pool, click **Add Dataset**, name it `navidrome-wrapped` and set **Dataset Preset** to `Apps`. This gives the `apps` user (UID 568) write access.
2. Go to **Apps → Discover Apps**. Open the **⋮** menu (top right) and choose **Install via YAML**.
3. Name it `navidrome-wrapped` and paste the YAML below. Fill in your values, and change `tank` to your pool name:
   ```yaml
   services:
     wrapped:
       image: ghcr.io/quinta0/navidrome-wrapped:latest
       user: "568:568"
       ports:
         - "8085:8080"
       volumes:
         - /mnt/tank/navidrome-wrapped:/data
       environment:
         LB_USER: ""
         LB_TOKEN: ""
         LASTFM_USER: ""
         LASTFM_KEY: ""
         ND_URL: "http://192.168.1.10:4533"
         ND_USER: ""
         ND_PASS: ""
       restart: unless-stopped
   ```
   Leave unused sources empty. You can also add `REFRESH` or `THEME_SEED` here.
4. Click **Save**. Wait for the app to show **Running**.
5. Open the app's **Logs**. The first build can take several minutes. It's done when you see `listens -> /data/site/index.html`.
6. Open `http://<truenas-ip>:8085`.

On TrueNAS 24.04 or earlier, use **Custom App** instead and enter the same image, port, host path and environment variables in the form.

On either system, `ND_URL` only needs to be reachable from the container. Songs and covers are copied into the page, so your Navidrome doesn't have to be public. To share your recap, put port 8085 behind your reverse proxy (see [Sharing your recap](#sharing-your-recap)).

## Configuration

| Variable | |
|---|---|
| `LB_USER`, `LB_TOKEN` | ListenBrainz username; the token is optional |
| `LASTFM_USER`, `LASTFM_KEY` | Last.fm username + [API key](https://www.last.fm/api/account/create) |
| `ND_URL`, `ND_USER`, `ND_PASS` | Navidrome. A LAN address is fine, since the container fetches everything it needs |
| `REFRESH` | `both` (default), `monthly` or `yearly`. Monthly recaps cover one month and are built on the 1st of the next one; the yearly recap covers Jan 1 to Dec 31 and is built on Jan 1. On startup, the month and year in progress are built too |
| `THEME_SEED` | Keeps a look you like. Every run prints its seed (it's also in the page's `<meta name=generator>`); set this to reuse that design |

You need at least one of ListenBrainz or Last.fm. If you scrobble to both, duplicate plays are removed. Navidrome is optional, but it provides song lengths, genres, library stats, the audio and the covers.

## Sharing your recap

Each person runs their own container, pointed at their own Navidrome server. To share yours:

- **Expose it:** put the container behind your reverse proxy (Caddy, Traefik, nginx, Cloudflare Tunnel...) and send the link. Anyone who has the link can listen to the songs in your recap.
- **Send it as a file:** zip `data/site/` and send it, or upload it to any static host. It works when opened from disk.
- **Just the card:** tap "Save image" on the last slide.

## Run without Docker

```sh
export LB_USER=... ND_URL=... ND_USER=... ND_PASS=...
python3 wrapped.py --year 2026 --out wrapped   # then open wrapped/index.html
python3 wrapped.py --year 2026 --month 11 --out wrapped-nov   # just November
```

Requires Python 3.12+. Run the tests with `python3 test_wrapped.py`.

## Notes

- Delete `data/cache/` after importing older history, so the new artists card is recomputed.
- Songs are matched to your Navidrome library by artist and title. A slide has no audio if its song isn't in your library.
- Navidrome converts the audio to MP3 with ffmpeg, so ffmpeg must be available to your Navidrome server (the official image includes it).

## Fonts

`fonts/` contains variable fonts from Google Fonts, licensed under the [SIL Open Font License 1.1](https://openfontlicense.org) (each family's license is in `fonts/LICENSES/`). Each page embeds only the two fonts its design uses, so it works offline. To change the set, edit the lists in `scripts/fetch_fonts.py` and run it.

## License

Code: [GPL-3.0](LICENSE). Free to use, share and modify; modified versions must stay open under the same license. Bundled fonts: OFL-1.1 (see above).
