# 41 vibe check (free skill)

A Claude Code skill that reads the Claude Code sessions already on your computer and shows where the money goes.

- A **vibe score from 0 to 100** and one of **5 levels**
- **8 checks** of how you work with Claude Code
- The **top 3 improvements**, each with a saving
- Your usage as a **multiple of your plan**

## Privacy

It runs 100% locally and sends nothing. There is no account, no network call and no telemetry. The report is an
HTML file on your own disk.

## Requirements

- Claude Code
- Python 3.9 or newer (most Macs and Linux machines have it)

## Install

Pick one.

### a) Clone it

macOS or Linux:

```
git clone https://github.com/mcbader93/41-vibecheck-skill ~/.claude/skills/vibecheck
```

Windows PowerShell:

```
git clone https://github.com/mcbader93/41-vibecheck-skill "$HOME\.claude\skills\vibecheck"
```

### b) Download the ZIP

Use **Code > Download ZIP** on GitHub, unzip it, and rename the folder to `vibecheck` inside `~/.claude/skills`.

macOS or Linux (adjust the ZIP path if needed):

```
mkdir -p ~/.claude/skills
unzip ~/Downloads/41-vibecheck-skill-main.zip -d ~/.claude/skills
mv ~/.claude/skills/41-vibecheck-skill-main ~/.claude/skills/vibecheck
```

Windows PowerShell:

```
Expand-Archive "$HOME\Downloads\41-vibecheck-skill-main.zip" "$HOME\.claude\skills"
Rename-Item "$HOME\.claude\skills\41-vibecheck-skill-main" "vibecheck"
```

### c) Drag it into Claude Code

Drag the folder or the ZIP into Claude Code and say: `Install this skill`.

## Use it

Type `/vibecheck` in Claude Code. If it is not found, restart Claude Code. It prints a summary and saves an HTML
report to `~/vibecheck/report-<date>.html`.

Options (add them after `/vibecheck`):

```
/vibecheck --days 7          only the last 7 days
/vibecheck --project .       only the current project
/vibecheck --bill 120        your real bill in USD, to show coverage
/vibecheck --profile list    price profile (default: list)
/vibecheck --experimental    include experimental checks
```

To update, run `git pull` inside the skill folder. To remove it, delete the `vibecheck` folder.

## Troubleshooting

- `python3: command not found`: macOS run `xcode-select --install`. Linux: install `python3` with your package
  manager. Windows: install Python 3 from python.org or the Microsoft Store, then Claude can use `py -3`.
- "No Claude Code sessions found": Claude Code deletes old sessions after 30 days by default. If you moved your
  config, set `CLAUDE_CONFIG_DIR`.
- Report does not open: open the newest `~/vibecheck/report-<date>.html` by hand.

## More

vibe check Pro for teams: [get41.ai/vibecheck](https://get41.ai/vibecheck)

## License

MIT, see `LICENSE`.
