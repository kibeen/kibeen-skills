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
| `superpowers-lab` | superpowers 실험 스킬 4종 (tmux 대화형 명령, mcp-cli, 중복 함수 탐지, windows-vm) | [obra/superpowers-lab](https://github.com/obra/superpowers-lab), `51111f7` |
| `skill-seekers` | 문서·레포·PDF 를 스킬로 변환 (skill-builder + 명령 3종 + MCP). `pip install "skill-seekers[mcp]"` 필요 | [yusufkaraaslan/Skill_Seekers](https://github.com/yusufkaraaslan/Skill_Seekers) `distribution/claude-plugin`, `5b5d8df` |
| `repomix-mcp` | Repomix MCP 서버 (`npx repomix@latest --mcp`, 업스트림이 latest 를 씀) | [yamadashy/repomix](https://github.com/yamadashy/repomix), `758c3d7` |
| `repomix-commands` | `/pack-local`, `/pack-remote` 명령 | 위와 같음 |
| `repomix-explorer` | Repomix 기반 레포 분석 에이전트와 명령 | 위와 같음 |
| `canvas-design` | 포스터·아트워크 시각 디자인 스킬 | [anthropics/skills](https://github.com/anthropics/skills), `2c5958e` |
| `algorithmic-art` | p5.js 제너러티브 아트 스킬 | 위와 같음 |
| `design-skills` | 디자인 스킬 6종 (baseline-ui, emil-design-eng, interface-design, 접근성·메타데이터·모션 수정). 라이선스 표기 없음 | [master5d/claude-design-skills](https://github.com/master5d/claude-design-skills), `5cf7b69` |
| `content-research-writer` | 리서치·인용·개요 피드백 글쓰기 스킬. 라이선스 표기 없음 | [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills), `be2a406` |
| `systematic-debugging` | superpowers 의 스킬 1개만 단독 설치 (`superpowers` 와 함께 설치하지 말 것) | [obra/superpowers](https://github.com/obra/superpowers), `22f0b46` |
| `test-driven-development` | superpowers 의 스킬 1개만 단독 설치 (`superpowers` 와 함께 설치하지 말 것) | 위와 같음 |
| `tapestry` | 생산성 스킬 7종 (learn-this, ship-learn-next, youtube-transcript, article-extractor, scrum-sage, session-log, unblock-action) | [michalparkola/tapestry-skills](https://github.com/michalparkola/tapestry-skills), `80e1dc5` |
| `hyperframes` | HyperFrames (HTML 로 영상 작성·렌더) 스킬 모음 | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes), `7bf6599` |
| `impeccable` | 프런트엔드 디자인 어휘·리뷰 스킬 + 에이전트 4종 + 훅 3개 (SessionStart, Edit/Write 후, Stop) | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) `plugin/`, `613fbf8` |
| `frontend-design` | Anthropic 공식 frontend-design 스킬 | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official), `0412be7` |

```
/plugin install <이름>@kibeen-skills
```

`playwright` 를 뺀 플러그인은 업스트림 레포를 직접 가리키며 커밋 SHA 로 고정돼 있다. 업스트림을 따라가려면
`.claude-plugin/marketplace.json` 의 `sha` 를 새 커밋으로 바꾼다.

새 플러그인은 `plugins/<이름>/` 에 두고 `.claude-plugin/marketplace.json` 의 `plugins` 에 추가한다.


## k-skill (한국 생활·업무 스킬)
[NomaDamas/k-skill](https://github.com/NomaDamas/k-skill) (MIT) 에서 고른 55개 스킬을 각각 별도 플러그인으로 넣었다.
업스트림 `plugin.json` 이 90여 개 스킬 전체를 선언해 일부만 묶을 수 없기 때문에, 스킬 폴더 하나씩을 `git-subdir` 로 가리킨다 (커밋 `9766d20`).

`railway-timetable`, `express-bus-booking`, `intercity-bus-booking`, `flight-ticket-search`, `myrealtrip-search`, `seoul-subway-arrival`, `korean-transit-route`, `kakao-map`, `parking-lot-search`, `ev-charger-nearby`, `real-estate-search`, `housing-official-price`, `gongsijiga-search`, `court-auction-notice-search`, `korean-law-search`, `iros-registry-automation`, `korean-stock-search`, `k-dart`, `company-analysis`, `toss-investment`, `daishin-report-search`, `kosis-stats`, `bok-ecos-stats`, `government-bond-analysis`, `multi-asset-morning-briefing`, `market-event-impact`, `emergency-room-beds`, `kpic-drug-search`, `mfds-food-safety`, `coupang-product-search`, `danawa-price-search`, `daiso-product-search`, `market-kurly-search`, `olive-young-search`, `ohou-today-deal`, `daangn-used-goods-search`, `delivery-tracking`, `kakao-bar-nearby`, `korean-cinema-search`, `ticket-availability`, `kopis-performance-search`, `library-book-search`, `naver-news-search`, `hankookilbo-news`, `naver-blog-research`, `geeknews-search`, `korean-humanizer`, `korea-weather`, `seoul-weather-risk`, `fine-dust-location`, `korean-holiday-calendar`, `zipcode-search`, `public-restroom-nearby`, `hwp`, `rhwp-edit`

전부 설치 (bash):
```bash
for p in railway-timetable express-bus-booking intercity-bus-booking flight-ticket-search myrealtrip-search seoul-subway-arrival korean-transit-route kakao-map parking-lot-search ev-charger-nearby real-estate-search housing-official-price gongsijiga-search court-auction-notice-search korean-law-search iros-registry-automation korean-stock-search k-dart company-analysis toss-investment daishin-report-search kosis-stats bok-ecos-stats government-bond-analysis multi-asset-morning-briefing market-event-impact emergency-room-beds kpic-drug-search mfds-food-safety coupang-product-search danawa-price-search daiso-product-search market-kurly-search olive-young-search ohou-today-deal daangn-used-goods-search delivery-tracking kakao-bar-nearby korean-cinema-search ticket-availability kopis-performance-search library-book-search naver-news-search hankookilbo-news naver-blog-research geeknews-search korean-humanizer korea-weather seoul-weather-risk fine-dust-location korean-holiday-calendar zipcode-search public-restroom-nearby hwp rhwp-edit; do claude plugin install "$p@kibeen-skills"; done
```

주의:
- 각 SKILL.md 는 껍데기이고, 실행 시 `npx -y @nomadamas/k-skill@0 instruct <스킬>` 로 **npm 패키지에서 지침을 받아온다**.
  git 커밋은 고정돼 있어도 실제 동작은 npm `@0` 범위 최신 버전(현재 0.11.2)을 따른다. Node.js 18+ 필요.
- 일부 스킬(kakao-map, parking-lot-search, real-estate-search, korean-law-search, korean-stock-search, mfds-food-safety,
  coupang-product-search, library-book-search, naver-news-search, fine-dust-location, korean-holiday-calendar)은
  운영자 호스팅 프록시 `https://k-skill-proxy.nomadamas.org` 로 질의를 보낸다. 직접 운영하려면 `KSKILL_PROXY_BASE_URL` 을 지정한다.
- 인증이 필요한 스킬의 초기 설정은 업스트림 `k-skill-setup` 스킬이 담당한다(여기에는 넣지 않았다).

## Windows 에서 설치할 때
`gsd-core`, `hyperframes` 처럼 파일 경로가 깊은 업스트림은 Windows 경로 길이 제한(260자)에 걸려
`Filename too long` 으로 설치가 실패할 수 있다. 설치 전에 한 번 실행한다.
```
git config --global core.longpaths true
```

## 마켓플레이스 밖에서 설치하는 도구
아래 둘은 이 마켓플레이스에 넣지 않았다. 각 업스트림의 설치 프로그램이 CLI·worker 설정까지 함께 하기 때문이다.

| 도구 | 설치 | 이유 |
|---|---|---|
| graphify | `uv tool install graphifyy && graphify install` | 스킬 파일이 플러그인 구조가 아니고, 설치 프로그램이 Python CLI 와 스킬을 함께 등록한다. [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) |
| claude-mem | `/plugin marketplace add thedotmack/claude-mem` 후 `/plugin install claude-mem`, 또는 `npx claude-mem install` | 플러그인 이름이 서드파티 마켓플레이스 예약어(`claude-`)에 걸리고, 훅이 업스트림 마켓플레이스 경로를 가정한다. 모든 도구 사용을 기록하는 훅 9종과 로컬 worker 가 돌며, 익명 사용 통계가 기본으로 켜져 있다(`npx claude-mem telemetry disable`). [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) |
