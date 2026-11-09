# kibeen-skills

kibeen 개인 Claude Code 플러그인 마켓플레이스 (private).

## 마켓플레이스로 설치
```
/plugin marketplace add kibeen/kibeen-skills
```
## 플러그인

| 이름 | 내용 | 출처 (고정 커밋) |
|---|---|---|
| `playwright` | Playwright MCP 서버 (`@playwright/mcp@0.0.84`) | `plugins/playwright/` |
| `agent-browser` | 브라우저 자동화 CLI 스킬. `npm i -g agent-browser && agent-browser install` 필요 | [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser), `4b0e9f0` |
| `find-skills` | 설치할 만한 스킬을 찾아 주는 스킬 | [vercel-labs/skills](https://github.com/vercel-labs/skills), `d3701c1` |
| `gsd-core` | GSD Core (구 get-shit-done). 스펙 주도 개발 스킬 72종 + 훅, `/gsd-core:gsd-<명령>` | [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core), `6559d13` |
| `taste-skill` | 프런트엔드 디자인 품질 스킬 (`design-taste-frontend`) | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill), `f6b7657` |
| `mcp-builder` | MCP 서버 설계·구현 가이드 스킬 | [anthropics/skills](https://github.com/anthropics/skills), `2c5958e` |
| `superpowers` | TDD·디버깅·계획·코드 리뷰 개발 방법론 스킬 모음 + SessionStart 훅 | [obra/superpowers](https://github.com/obra/superpowers), `22f0b46` |
| `ui-ux-pro-max` | UI/UX 디자인 인텔리전스 스킬 7종 (스타일·팔레트·폰트·차트 DB) | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), `4f2dbb6` |
| `caveman` | 응답 압축 모드. SessionStart·SubagentStart·UserPromptSubmit·SessionEnd 훅으로 항상 켜짐 (Node 필요) | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman), `3dc497a` |

```
/plugin install <이름>@kibeen-skills
```

`playwright` 를 뺀 플러그인은 업스트림 레포를 직접 가리키며 커밋 SHA 로 고정돼 있다. 업스트림을 따라가려면
`.claude-plugin/marketplace.json` 의 `sha` 를 새 커밋으로 바꾼다.

새 플러그인은 `plugins/<이름>/` 에 두고 `.claude-plugin/marketplace.json` 의 `plugins` 에 추가한다.
