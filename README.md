# kibeen-skills

kibeen 개인 Claude Code 플러그인 마켓플레이스 (private).

- Anthropic 공식 마켓플레이스(`claude-plugins-official`)에 있는 플러그인은 여기에 복사하지 않는다.
  `settings/claude-settings.json` 의 `enabledPlugins` 에 "무엇을 켤지"만 적고, 설치와 업데이트는 공식 마켓플레이스를 따른다.
- 그 밖의 외부 플러그인은 업스트림 레포를 커밋 SHA 로 고정해 가리키고, GitHub Actions 가 매일 그 SHA 를 업스트림 최신으로 올린다.

## 새 머신 설정 (1회)
```bash
gh auth login                                   # private repo 접근
git clone https://github.com/kibeen/kibeen-skills.git ~/kibeen-skills
node ~/kibeen-skills/scripts/apply-settings.mjs --dry-run   # 바뀔 내용 확인
node ~/kibeen-skills/scripts/apply-settings.mjs             # ~/.claude/settings.json 에 병합 (백업 생성)
```
`apply-settings.mjs` 는 `settings/claude-settings.json` 의 두 키만 병합한다.

- `extraKnownMarketplaces`: `claude-plugins-official`, `kibeen-skills`, `kraken-skills`, `thedotmack`(claude-mem) 을
  `autoUpdate: true` 로 선언한다. 서드파티 마켓플레이스는 기본이 자동 업데이트 꺼짐이라 이 선언이 있어야 업데이트를 따라간다.
- `enabledPlugins`: 목록의 플러그인을 켠다. 설치되지 않은 플러그인은 다음 시작 때 자동으로 받는다.
  그 머신에서 `false` 로 꺼 둔 플러그인은 다시 켜지 않는다. 마켓플레이스만 선언하려면 `--marketplaces-only`.

목록을 바꾸려면 `settings/claude-settings.json` 을 고쳐 push 하고, 각 머신에서 `git pull` 후 `apply-settings.mjs` 를 다시 실행한다.

## 업데이트가 따라가는 방식
1. **공식 플러그인**: `claude-plugins-official` 이 갱신되면 자동 업데이트(공식 마켓플레이스는 기본 켜짐)로 따라간다.
2. **이 마켓플레이스의 외부 플러그인**: `.github/workflows/sync-upstream.yml` 이 매일 06:17 KST 에 `scripts/sync-upstream.mjs` 를 실행한다.
   - `github`/`url` 소스: 기본 브랜치(또는 `ref`) 최신 커밋으로 `sha` 를 올린다.
   - `git-subdir` 소스: 해당 폴더를 바꾼 최신 커밋으로 올린다. k-skill 처럼 큰 레포는 그 스킬 폴더가 바뀔 때만 움직인다.
   - `mcpServers` 의 `패키지@x.y.z` 고정 버전: npm 최신 안정 버전으로 올린다.
   - 바뀐 것이 있으면 `chore: sync upstream pins` 로 커밋한다. 각 머신은 자동 업데이트로 받는다.
3. Claude Code 는 플러그인 버전을 `plugin.json` 의 `version` → 마켓플레이스 항목 `version` → 소스 커밋 SHA 순으로 정한다.
   그래서 이 마켓플레이스 항목에는 `version` 을 적지 않는다. 업스트림 `plugin.json` 에 `version` 이 있는 플러그인은
   업스트림이 그 버전을 올릴 때 업데이트된다(업스트림 릴리스 규칙을 그대로 따른다).

수동 실행: Actions 탭의 "Sync upstream pins" → Run workflow, 또는 로컬에서
`GITHUB_TOKEN=$(gh auth token) node scripts/sync-upstream.mjs --dry-run`.
릴리스 직후 버전을 바로 받지 않으려면 저장소 변수 `MIN_AGE_DAYS` 를 설정한다(예: 3 → 3일 이상 지난 커밋·버전만 채택).

## 공식 마켓플레이스 플러그인 (`enabledPlugins`)
`playwright`, `superpowers`, `hyperframes`, `frontend-design`, `canva`, `chrome-devtools-mcp`, `firecrawl`, `notion`, `supabase`, `vercel`
(모두 `@claude-plugins-official`)

- `canva`, `notion`, `supabase`, `vercel` 은 처음 쓸 때 각 계정 로그인, `firecrawl` 은 API 키가 필요하다.
- `vercel` 은 SessionStart·PostToolUse·SessionEnd 훅이 있고 스킬이 37개다. `superpowers` 는 SessionStart 훅이 있다.

## 이 마켓플레이스의 플러그인
```
/plugin install <이름>@kibeen-skills
```

| 이름 | 내용 | 업스트림 |
|---|---|---|
| `agent-browser` | 브라우저 자동화 CLI 스킬. `npm i -g agent-browser && agent-browser install` 필요 | [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser) |
| `find-skills` | 설치할 만한 스킬을 찾아 주는 스킬 | [vercel-labs/skills](https://github.com/vercel-labs/skills) |
| `gsd-core` | GSD Core (구 get-shit-done). 스펙 주도 개발 스킬 72종 + 훅, `/gsd-core:gsd-<명령>` | [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core) |
| `taste-skill` | 프런트엔드 디자인 품질 스킬 (`design-taste-frontend`) | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) |
| `mcp-builder` | MCP 서버 설계·구현 가이드 스킬 | [anthropics/skills](https://github.com/anthropics/skills) `skills/mcp-builder` |
| `canvas-design` | 포스터·아트워크 시각 디자인 스킬 | [anthropics/skills](https://github.com/anthropics/skills) `skills/canvas-design` |
| `algorithmic-art` | p5.js 제너러티브 아트 스킬 | [anthropics/skills](https://github.com/anthropics/skills) `skills/algorithmic-art` |
| `ui-ux-pro-max` | UI/UX 디자인 인텔리전스 스킬 7종 (스타일·팔레트·폰트·차트 DB) | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) |
| `caveman` | 응답 압축 모드. SessionStart·SubagentStart·UserPromptSubmit·SessionEnd 훅으로 항상 켜짐 (Node 필요) | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) |
| `superpowers-lab` | superpowers 실험 스킬 4종 (tmux 대화형 명령, mcp-cli, 중복 함수 탐지, windows-vm) | [obra/superpowers-lab](https://github.com/obra/superpowers-lab) |
| `systematic-debugging` | superpowers 의 스킬 1개만 단독 설치 (`superpowers` 와 함께 켜지 말 것) | [obra/superpowers](https://github.com/obra/superpowers) `skills/systematic-debugging` |
| `test-driven-development` | superpowers 의 스킬 1개만 단독 설치 (`superpowers` 와 함께 켜지 말 것) | [obra/superpowers](https://github.com/obra/superpowers) `skills/test-driven-development` |
| `skill-seekers` | 문서·레포·PDF 를 스킬로 변환 (skill-builder + 명령 3종 + MCP). `pip install "skill-seekers[mcp]"` 필요 | [yusufkaraaslan/Skill_Seekers](https://github.com/yusufkaraaslan/Skill_Seekers) `distribution/claude-plugin` |
| `repomix-mcp` | Repomix MCP 서버 (업스트림 설정이 `repomix@latest` 를 씀) | [yamadashy/repomix](https://github.com/yamadashy/repomix) |
| `repomix-commands` | `/pack-local`, `/pack-remote` 명령 | 위와 같음 |
| `repomix-explorer` | Repomix 기반 레포 분석 에이전트와 명령 | 위와 같음 |
| `design-skills` | 디자인 스킬 6종 (baseline-ui, emil-design-eng, interface-design, 접근성·메타데이터·모션 수정). 라이선스 표기 없음 | [master5d/claude-design-skills](https://github.com/master5d/claude-design-skills) |
| `content-research-writer` | 리서치·인용·개요 피드백 글쓰기 스킬. 라이선스 표기 없음 | [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) |
| `tapestry` | 생산성 스킬 7종 (learn-this, ship-learn-next, youtube-transcript, article-extractor, scrum-sage, session-log, unblock-action) | [michalparkola/tapestry-skills](https://github.com/michalparkola/tapestry-skills) |
| `impeccable` | 프런트엔드 디자인 어휘·리뷰 스킬 + 에이전트 4종 + 훅 3개 (SessionStart, Edit/Write 후, Stop) | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) `plugin/` |
| `perplexity` | Perplexity 웹 검색·추론·리서치 MCP. 환경변수 `PERPLEXITY_API_KEY` 필요 | [perplexityai/modelcontextprotocol](https://github.com/perplexityai/modelcontextprotocol) |
| `higgsfield` | Higgsfield 이미지·영상 생성 스킬 9종 (MCP 아님). `higgsfield` CLI 설치와 `higgsfield auth login` 필요 | [higgsfield-ai/skills](https://github.com/higgsfield-ai/skills) |

현재 고정 커밋은 `.claude-plugin/marketplace.json` 의 각 `source.sha` 에 있다.

## k-skill (한국 생활·업무 스킬)
[NomaDamas/k-skill](https://github.com/NomaDamas/k-skill) (MIT) 에서 고른 55개 스킬을 각각 별도 플러그인으로 넣었다.
업스트림 `plugin.json` 이 90여 개 스킬 전체를 선언해 일부만 묶을 수 없기 때문에, 스킬 폴더 하나씩을 `git-subdir` 로 가리킨다.

`railway-timetable`, `express-bus-booking`, `intercity-bus-booking`, `flight-ticket-search`, `myrealtrip-search`, `seoul-subway-arrival`, `korean-transit-route`, `kakao-map`, `parking-lot-search`, `ev-charger-nearby`, `real-estate-search`, `housing-official-price`, `gongsijiga-search`, `court-auction-notice-search`, `korean-law-search`, `iros-registry-automation`, `korean-stock-search`, `k-dart`, `company-analysis`, `toss-investment`, `daishin-report-search`, `kosis-stats`, `bok-ecos-stats`, `government-bond-analysis`, `multi-asset-morning-briefing`, `market-event-impact`, `emergency-room-beds`, `kpic-drug-search`, `mfds-food-safety`, `coupang-product-search`, `danawa-price-search`, `daiso-product-search`, `market-kurly-search`, `olive-young-search`, `ohou-today-deal`, `daangn-used-goods-search`, `delivery-tracking`, `kakao-bar-nearby`, `korean-cinema-search`, `ticket-availability`, `kopis-performance-search`, `library-book-search`, `naver-news-search`, `hankookilbo-news`, `naver-blog-research`, `geeknews-search`, `korean-humanizer`, `korea-weather`, `seoul-weather-risk`, `fine-dust-location`, `korean-holiday-calendar`, `zipcode-search`, `public-restroom-nearby`, `hwp`, `rhwp-edit`

전부 설치 (bash):
```bash
for p in railway-timetable express-bus-booking intercity-bus-booking flight-ticket-search myrealtrip-search seoul-subway-arrival korean-transit-route kakao-map parking-lot-search ev-charger-nearby real-estate-search housing-official-price gongsijiga-search court-auction-notice-search korean-law-search iros-registry-automation korean-stock-search k-dart company-analysis toss-investment daishin-report-search kosis-stats bok-ecos-stats government-bond-analysis multi-asset-morning-briefing market-event-impact emergency-room-beds kpic-drug-search mfds-food-safety coupang-product-search danawa-price-search daiso-product-search market-kurly-search olive-young-search ohou-today-deal daangn-used-goods-search delivery-tracking kakao-bar-nearby korean-cinema-search ticket-availability kopis-performance-search library-book-search naver-news-search hankookilbo-news naver-blog-research geeknews-search korean-humanizer korea-weather seoul-weather-risk fine-dust-location korean-holiday-calendar zipcode-search public-restroom-nearby hwp rhwp-edit; do claude plugin install "$p@kibeen-skills"; done
```

주의:
- 각 SKILL.md 는 껍데기이고, 실행 시 `npx -y @nomadamas/k-skill@0 instruct <스킬>` 로 **npm 패키지에서 지침을 받아온다**.
  실제 동작은 npm `@0` 범위 최신 버전을 따른다. Node.js 18+ 필요.
- 일부 스킬(kakao-map, parking-lot-search, real-estate-search, korean-law-search, korean-stock-search, mfds-food-safety,
  coupang-product-search, library-book-search, naver-news-search, fine-dust-location, korean-holiday-calendar)은
  운영자 호스팅 프록시 `https://k-skill-proxy.nomadamas.org` 로 질의를 보낸다. 직접 운영하려면 `KSKILL_PROXY_BASE_URL` 을 지정한다.
- 인증이 필요한 스킬의 초기 설정은 업스트림 `k-skill-setup` 스킬이 담당한다(여기에는 넣지 않았다).

## Windows 에서 설치할 때
`gsd-core` 처럼 파일 경로가 깊은 업스트림은 Windows 경로 길이 제한(260자)에 걸려
`Filename too long` 으로 설치가 실패할 수 있다. 설치 전에 한 번 실행한다.
```
git config --global core.longpaths true
```

## 마켓플레이스 밖의 도구

| 도구 | 설치 | 업데이트 |
|---|---|---|
| claude-mem | `claude plugin install claude-mem@thedotmack` (마켓플레이스는 `apply-settings.mjs` 가 선언) | `thedotmack` 마켓플레이스 자동 업데이트 |
| graphify | `uv tool install graphifyy && graphify install` | `uv tool upgrade graphifyy` 후 `graphify install` |

- claude-mem 은 플러그인 이름이 서드파티 마켓플레이스 예약어(`claude-`)에 걸리고 훅이 업스트림 마켓플레이스 경로를 가정해서 여기에 넣지 않았다.
  모든 도구 사용을 기록하는 훅 9종과 로컬 worker 가 돌며, 익명 사용 통계가 기본으로 켜져 있다(`npx claude-mem telemetry disable`).
- graphify 는 스킬 파일이 플러그인 구조가 아니고, 설치 프로그램이 Python CLI 와 스킬을 함께 등록한다.

## 새 플러그인 추가
- 공식 마켓플레이스에 있으면 `settings/claude-settings.json` 의 `enabledPlugins` 에 `<이름>@claude-plugins-official` 로 추가한다.
- 아니면 `.claude-plugin/marketplace.json` 의 `plugins` 에 업스트림 소스와 `sha` 를 넣는다(`version` 은 적지 않는다).
  추가 후 `claude plugin validate .` 로 검사한다.
