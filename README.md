# kibeen-skills

kibeen 개인 Claude Code 환경 설정 (private). 도구는 출처에 따라 세 갈래로 관리한다.

| 갈래 | 어디서 설치 | 정의·업데이트 주체 |
|---|---|---|
| 공식 마켓플레이스 플러그인 | `claude-plugins-official` | Anthropic |
| 원본 마켓플레이스 플러그인 | 각 도구의 자체 마켓플레이스 | 각 도구 개발자 |
| 이 마켓플레이스의 플러그인 | `kibeen-skills` | 업스트림 파일 + 이 레포의 정의 (원본에 없는 묶음만) |

이 레포에는 업스트림 파일을 복사하지 않는다. 원본이 제공하는 플러그인은 원본을 그대로 쓰고,
`kibeen-skills` 에는 원본으로 해결할 수 없는 것(큰 묶음에서 일부만 고르기, 마켓플레이스가 없는 레포)만 둔다.

## 새 머신 설정 (1회)
```bash
gh auth login                                   # private repo 접근
gh auth setup-git                               # 필수: 백그라운드 자동 업데이트가 이 인증 도우미로 private repo 를 받는다
git clone https://github.com/kibeen/kibeen-skills.git ~/kibeen-skills
node ~/kibeen-skills/scripts/apply-settings.mjs --dry-run   # 바뀔 내용 확인
node ~/kibeen-skills/scripts/apply-settings.mjs             # ~/.claude/settings.json 에 병합 (백업 생성)
```
Windows 는 먼저 `git config --global core.longpaths true` 를 실행한다(아래 "Windows" 참고).

`apply-settings.mjs` 는 `settings/claude-settings.json` 의 두 키만 병합한다.

- `extraKnownMarketplaces`: 공식·원본·이 레포의 마켓플레이스 13개를 `autoUpdate: true` 로 선언한다.
  서드파티 마켓플레이스는 기본이 자동 업데이트 꺼짐이라 이 선언이 있어야 업데이트를 따라간다.
  선언된 마켓플레이스는 다음 Claude Code 시작 때 받아진다.
- `enabledPlugins`: 목록의 플러그인을 켠다. 설치되지 않은 플러그인은 다음 시작 때 자동으로 받는다.
  그 머신에서 `false` 로 꺼 둔 플러그인은 다시 켜지 않는다. 마켓플레이스만 선언하려면 `--marketplaces-only`.

목록을 바꾸려면 `settings/claude-settings.json` 을 고쳐 push 하고, 각 머신에서 `git pull` 후 `apply-settings.mjs` 를 다시 실행한다.

## 업데이트가 따라가는 방식
- **공식·원본 마켓플레이스 플러그인**: 각 마켓플레이스가 갱신되면 자동 업데이트로 따라간다. 버전 규칙은 각 원본의 것을 따른다
  (원본 `plugin.json` 에 `version` 이 있으면 원본이 그 값을 올릴 때 업데이트된다).
- **이 마켓플레이스의 플러그인**: `.github/workflows/sync-upstream.yml` 이 매일 06:17 KST 에 `scripts/sync-upstream.mjs` 를 실행해
  각 `source.sha` 를 업스트림 최신 커밋으로 올리고 커밋한다(`git-subdir` 는 해당 폴더를 바꾼 최신 커밋).
  항목에 `version` 을 적지 않으므로 커밋 SHA 가 곧 버전이 되어, 바뀐 플러그인만 업데이트된다.
  - 수동 실행: Actions 탭 "Sync upstream pins" → Run workflow, 또는 `GITHUB_TOKEN=$(gh auth token) node scripts/sync-upstream.mjs --dry-run`.
  - 릴리스 직후 커밋을 바로 받지 않으려면 저장소 변수 `MIN_AGE_DAYS` 를 설정한다(예: 3 → 3일 이상 지난 커밋만 채택).

## 공식 마켓플레이스 플러그인 (`enabledPlugins` 로 켬)
`playwright`, `superpowers`, `hyperframes`, `frontend-design`, `canva`, `chrome-devtools-mcp`, `firecrawl`, `notion`, `supabase`, `vercel`
(모두 `@claude-plugins-official`)

- `canva`, `notion`, `supabase`, `vercel` 은 처음 쓸 때 각 계정 로그인, `firecrawl` 은 API 키가 필요하다.
- `vercel` 은 SessionStart·PostToolUse·SessionEnd 훅이 있고 스킬이 37개다. `superpowers` 는 SessionStart 훅이 있다.

## 원본 마켓플레이스 플러그인 (선언만, 설치는 필요할 때)
```
claude plugin install <플러그인 ID>
```

| 플러그인 ID | 내용 | 원본 |
|---|---|---|
| `perplexity@perplexity-mcp-server` | Perplexity 웹 검색·추론·리서치 MCP. 환경변수 `PERPLEXITY_API_KEY` 필요 | [perplexityai/modelcontextprotocol](https://github.com/perplexityai/modelcontextprotocol) |
| `agent-browser@agent-browser` | 브라우저 자동화 CLI 스킬. `npm i -g agent-browser && agent-browser install` 필요 | [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser) |
| `taste-skill@taste-skill` | 프런트엔드 디자인 품질 스킬 (`design-taste-frontend`) | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) |
| `ui-ux-pro-max@ui-ux-pro-max-skill` | UI/UX 디자인 인텔리전스 스킬 7종. `taste-skill` 과 역할이 겹친다 | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) |
| `impeccable@impeccable` | 프런트엔드 디자인 어휘·리뷰 스킬 + 에이전트 4종 + 훅 3개 | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) |
| `gsd-core@gsd-core` | GSD Core (구 get-shit-done). 스펙 주도 개발 스킬 72종 + 훅 | [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core) |
| `caveman@caveman` | 응답 압축 모드. 훅 4개로 항상 켜짐 (Node 필요). 평소엔 `claude plugin disable caveman@caveman` 권장 | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) |
| `higgsfield@higgsfield` | 이미지·영상 생성 스킬 9종 (MCP 아님). `higgsfield` CLI 와 `higgsfield auth login` 필요 | [higgsfield-ai/skills](https://github.com/higgsfield-ai/skills) |
| `repomix-mcp@repomix` | Repomix MCP 서버 | [yamadashy/repomix](https://github.com/yamadashy/repomix) |
| `repomix-commands@repomix` | `/pack-local`, `/pack-remote` 명령 | 위와 같음 |
| `repomix-explorer@repomix` | Repomix 기반 레포 분석 에이전트와 명령 | 위와 같음 |
| `claude-mem@thedotmack` | 세션 간 영구 기억. 도구 사용을 기록하는 훅 9종과 로컬 worker, 익명 사용 통계 기본 켜짐(`npx claude-mem telemetry disable`) | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) |

## 이 마켓플레이스의 플러그인
```
claude plugin install <이름>@kibeen-skills
```

| 이름 | 내용 | 여기에 두는 이유 | 업스트림 |
|---|---|---|---|
| `mcp-builder` | MCP 서버 설계·구현 가이드 스킬 | 원본은 여러 스킬 묶음 단위 | [anthropics/skills](https://github.com/anthropics/skills) `skills/mcp-builder` |
| `canvas-design` | 포스터·아트워크 시각 디자인 스킬 | 위와 같음 | [anthropics/skills](https://github.com/anthropics/skills) `skills/canvas-design` |
| `algorithmic-art` | p5.js 제너러티브 아트 스킬 | 위와 같음 | [anthropics/skills](https://github.com/anthropics/skills) `skills/algorithmic-art` |
| `systematic-debugging` | superpowers 의 스킬 1개 (`superpowers` 와 함께 켜지 말 것) | 원본은 superpowers 전체 단위 | [obra/superpowers](https://github.com/obra/superpowers) `skills/systematic-debugging` |
| `test-driven-development` | superpowers 의 스킬 1개 (`superpowers` 와 함께 켜지 말 것) | 위와 같음 | [obra/superpowers](https://github.com/obra/superpowers) `skills/test-driven-development` |
| `superpowers-lab` | superpowers 실험 스킬 4종 | 원본에 마켓플레이스 없음 | [obra/superpowers-lab](https://github.com/obra/superpowers-lab) |
| `skill-seekers` | 문서·레포·PDF 를 스킬로 변환 (skill-builder + 명령 3종 + MCP). `pip install "skill-seekers[mcp]"` 필요 | 원본에 Claude 마켓플레이스 없음 | [yusufkaraaslan/Skill_Seekers](https://github.com/yusufkaraaslan/Skill_Seekers) `distribution/claude-plugin` |
| `find-skills` | 설치할 만한 스킬을 찾아 주는 스킬 | 원본에 마켓플레이스 없음 | [vercel-labs/skills](https://github.com/vercel-labs/skills) |
| `design-skills` | 디자인 스킬 6종. 라이선스 표기 없음 | 원본에 마켓플레이스 없음 | [master5d/claude-design-skills](https://github.com/master5d/claude-design-skills) |
| `content-research-writer` | 리서치·인용·개요 피드백 글쓰기 스킬. 라이선스 표기 없음 | 원본에 마켓플레이스 없음 | [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) |
| `tapestry` | 생산성 스킬 7종 (learn-this, ship-learn-next, youtube-transcript 등) | 원본에 마켓플레이스 없음 | [michalparkola/tapestry-skills](https://github.com/michalparkola/tapestry-skills) |
| k-skill 55종 | 아래 참고 | 원본은 90여 개 전체 단위 | [NomaDamas/k-skill](https://github.com/NomaDamas/k-skill) |

현재 고정 커밋은 `.claude-plugin/marketplace.json` 의 각 `source.sha` 에 있다.

### k-skill (한국 생활·업무 스킬)
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

## Windows
원본 마켓플레이스는 레포 전체를 받는다. `gsd-core`, `claude-mem`, `repomix`, `ui-ux-pro-max-skill` 처럼 경로가 깊은 레포는
홈 경로가 길면 Windows 경로 길이 제한(260자)에 걸려 `Filename too long` 으로 실패할 수 있다. 먼저 한 번 실행한다.
```
git config --global core.longpaths true
```

## 마켓플레이스 밖의 도구
| 도구 | 설치 | 업데이트 |
|---|---|---|
| graphify | `uv tool install graphifyy && graphify install` | `uv tool upgrade graphifyy` 후 `graphify install` |

graphify 는 스킬 파일이 플러그인 구조가 아니고, 설치 프로그램이 Python CLI 와 스킬을 함께 등록한다.

## 새 도구 추가 규칙
1. 공식 마켓플레이스에 있으면 → `settings/claude-settings.json` 의 `enabledPlugins` 에 `<이름>@claude-plugins-official`.
2. 원본이 자체 마켓플레이스를 제공하면 → `extraKnownMarketplaces` 에 그 레포를 `autoUpdate: true` 로 추가하고, README 표에 플러그인 ID 를 적는다.
3. 둘 다 아니거나 일부만 골라야 하면 → `.claude-plugin/marketplace.json` 에 업스트림 소스와 `sha` 로 추가한다(`version` 은 적지 않는다).
   추가 후 `claude plugin validate .` 로 검사한다.
