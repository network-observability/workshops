# Pre-work email templates

Two emails for Packt to send before the session. Copy the body, fill the bracketed bits, send.

The point of both: the only thing that can go wrong on the day is an unprepared laptop, and the only fix is image pulls that happen *before* 09:00 EDT. Everything else is recoverable live.

---

## T-7 days

**Subject**: Before your workshop — 30 minutes of setup, best done this week

> Hi,
>
> You're booked on **Building a Network Observability Stack with Tools, Automation, and AI** on **Saturday 19 September, 09:00–12:00 EDT (14:00–17:00 Dublin)**.
>
> The whole workshop runs on your own laptop — a full observability stack in Docker, no shared backend, nothing to sign up for. That means about 30 minutes of setup, and it is much better done this week than at 08:55 on the day. The first run pulls 3–5 GB of container images; on hotel or conference Wi-Fi that is the difference between "ready" and "watching".
>
> **Start here**: <https://network-observability.github.io/workshops/packt/prework/>
>
> **What you need**
>
> - **Docker** with Compose v2 (Docker Desktop, Colima, OrbStack or Rancher Desktop all work). `docker compose version` should report v2 or later.
> - **[uv](https://docs.astral.sh/uv/)** for the Python tooling — one install command, and it brings its own Python.
> - **~5.5 GB of free RAM** while the stack is running, and **~5 GB of free disk** for images.
> - **Windows**: you must run everything inside **WSL 2**, not PowerShell. Docker Desktop with the WSL 2 backend. If you have never set WSL up, do it this week, not on the day.
>
> **Then run the preflight** — it checks Docker, Compose v2, RAM, disk, and that it can reach the image registries:
>
> ```bash
> git clone https://github.com/network-observability/workshops.git
> cd workshops
> uv sync --all-packages
> uv run nobs preflight
> ```
>
> If everything is green, bring the stack up once so the images are cached:
>
> ```bash
> uv run nobs packt up
> uv run nobs packt status     # repeat until every row says ok
> uv run nobs packt load-infrahub
> ```
>
> Then `uv run nobs packt down` and leave it. On the day it comes back in seconds.
>
> **Two ways to take the workshop.** If your laptop cannot run the stack — locked-down corporate machine, not enough RAM, no time this week — come anyway. Every command and every expected output is written out in the guides, we drive the whole session on screen, and Packt records it. You will get the ideas either way. The hands-on lane is better if you can manage it; the watching lane is not a consolation prize.
>
> See you on the 19th.

---

## T-2 days

**Subject**: Workshop on Saturday — reply if your preflight is red

> Hi,
>
> **Building a Network Observability Stack with Tools, Automation, and AI** is this **Saturday 19 September, 09:00–12:00 EDT (14:00–17:00 Dublin)**. Joining details are in your Packt account.
>
> If you have already run the preflight and brought the stack up once, you are done — nothing else to do. See you Saturday.
>
> If you have not, this is the moment. It is about 30 minutes, and most of that is images downloading and building in the background:
>
> ```bash
> git clone https://github.com/network-observability/workshops.git
> cd workshops
> uv sync --all-packages
> uv run nobs preflight
> uv run nobs packt up
> uv run nobs packt status     # repeat until every row says ok
> ```
>
> Full instructions: <https://network-observability.github.io/workshops/packt/prework/>
>
> **If anything comes back red, reply to this email with the preflight output** — the whole block, copied out of your terminal. We will look at them before Saturday. A red preflight two days out is fixable; a red one at 09:00 EDT is not, and we will not spend the session debugging individual machines.
>
> Common ones we can fix by email: Docker Desktop not running, Compose v1 still on PATH, low disk, a corporate proxy blocking `ghcr.io`, and WSL 2 not enabled on Windows.
>
> **Reminders**
>
> - **Windows = WSL 2 only.** Not PowerShell, not Git Bash.
> - **~5.5 GB free RAM, ~5 GB free disk** while the stack runs.
> - **The session is recorded** by Packt, and questions go through the Q&A panel in the Packt app during the session — not chat.
> - **If your laptop will not cooperate, come anyway.** Every command and its expected output is written out, we drive the whole thing on screen, and the take-home page lets you do the hands-on parts later at your own pace.
>
> See you Saturday.
