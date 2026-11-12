# kibeen-skills

kibeen 개인 Claude Code 환경 설정 (public). 도구는 출처에 따라 세 갈래로 관리한다.

| 갈래 | 어디서 설치 | 정의·업데이트 주체 |
|---|---|---|
| 공식 마켓플레이스 플러그인 | `claude-plugins-official` | Anthropic |
| 원본 마켓플레이스 플러그인 | 각 도구의 자체 마켓플레이스 | 각 도구 개발자 |
| 이 마켓플레이스의 플러그인 | `kibeen-skills` | 업스트림 파일 + 이 레포의 정의 (원본에 없는 묶음만) |

이 레포에는 업스트림 파일을 복사하지 않는다. 원본이 제공하는 플러그인은 원본을 그대로 쓰고,
`kibeen-skills` 에는 원본으로 해결할 수 없는 것(큰 묶음에서 일부만 고르기, 마켓플레이스가 없는 레포)만 둔다.
역할이 겹치는 도구는 분야마다 하나만 둔다: 개발 방법론 `superpowers`, 프런트엔드 디자인 `taste-skill`, 브라우저 제어 `playwright`.

## 기본 도구 한 번에 설치 (`kibeen-skills` 플러그인)
`kibeen-skills` 플러그인 는 내용 없이 `dependencies` 만 가진 묶음 플러그인이다. 설치하면 기본 도구가 함께 설치된다.
```
claude plugin marketplace add kibeen/kibeen-skills
claude plugin marketplace add Leonxlnx/taste-skill        # 다른 마켓플레이스 의존성은 그 마켓플레이스가 등록돼 있어야 받는다
claude plugin install kibeen-skills@kibeen-skills
claude plugin uninstall kibeen-skills@kibeen-skills --prune   # 지울 때: 함께 설치된 도구까지 정리
```
- 의존성 목록은 `plugins/kibeen-skills/.claude-plugin/plugin.json`. `settings/claude-settings.json` 의 `enabledPlugins` 와 같게 유지한다.
- 다른 마켓플레이스 의존성은 `.claude-plugin/marketplace.json` 의 `allowCrossMarketplaceDependenciesOn` 에 그 마켓플레이스가 있어야 한다.
- 이 방식은 설치만 한다. 다른 플러그인을 지우거나 끄는 것은 아래 `apply-settings.mjs` 로 한다.
- `kibeen-skills` 플러그인 의 SessionStart 훅이 이 레포에 새 커밋이 있을 때, 아니면 하루 한 번 이 머신을 설정에 맞춘다.
  설치·켜기·제거를 모두 자동 적용하고(설정 백업 생성), 무엇을 했는지 한 줄 알림을 띄운다. 모델 컨텍스트에는 넣지 않는다.
  새로 켠 플러그인은 다음 세션부터 쓸 수 있다.
- 자동 적용 대신 알림만 받으려면 환경변수 `KIBEEN_AUTO_APPLY=0`. 수동 확인은
  `node ~/.claude/plugins/marketplaces/kibeen-skills/scripts/apply-settings.mjs --dry-run`.
- 제거 목록(`retired`)에 있는 도구는 그 머신에서 직접 다시 설치해도 다음 동기화 때 다시 제거된다.

## 답변 지침 (모든 머신에 자동 적용)
`settings/CLAUDE.kibeen.md` 의 지침을 `apply-settings.mjs` 가 각 머신의 `~/.claude/CLAUDE.md` 에 관리 블록
(`<!-- BEGIN kibeen-skills ... -->` ~ `<!-- END kibeen-skills -->`)으로 넣는다. 블록 밖 내용은 건드리지 않고, 바꾸기 전에 백업한다.
`kibeen-skills` 플러그인 훅이 자동 동기화하므로 이 파일을 고쳐 push 하면 모든 머신에 반영된다. 파일을 지우면 블록도 지워진다.

## 새 머신 설정 (1회)
```bash
git clone https://github.com/kibeen/kibeen-skills.git ~/kibeen-skills
node ~/kibeen-skills/scripts/apply-settings.mjs --dry-run   # 바뀔 내용 확인
node ~/kibeen-skills/scripts/apply-settings.mjs             # 적용 (settings.json 백업 생성)
```
Windows 에서 홈 경로가 길면 먼저 `git config --global core.longpaths true` 를 실행한다(아래 "Windows" 참고).

`apply-settings.mjs` 가 하는 일:

1. **정리** (`claude` CLI 사용): `settings/claude-settings.json` 의 `retired` 에 적힌 마켓플레이스를 제거(그 플러그인도 함께 제거)하고
   플러그인을 제거한다. 이 마켓플레이스에서 빠진 `@kibeen-skills` 플러그인도 제거한다.
2. **병합**: `extraKnownMarketplaces` 를 `autoUpdate: true` 로 선언하고, `enabledPlugins` 의 플러그인을 켠다.
   설치되지 않은 플러그인은 다음 Claude Code 시작 때 자동으로 받는다. 그 머신에서 `false` 로 꺼 둔 플러그인은 다시 켜지 않는다.
   플러그인은 켜지 않고 정리와 마켓플레이스 선언만 하려면 `--marketplaces-only`.

**프로젝트 범위**: 한 프로젝트에만 적용하려면 그 프로젝트 폴더에서 `claude plugin install kibeen-skills@kibeen-skills --scope project`.
동기화 훅이 이를 알아보고 `<프로젝트>/.claude/settings.json` 과 `<프로젝트>/.claude/CLAUDE.md` 만 바꾼다(사용자 설정은 그대로).
프로젝트 설정의 플러그인은 시작할 때 자동으로 받아지지 않으므로, 스크립트가 `--scope project` 로 직접 추가·설치한다.
수동 실행: `node scripts/apply-settings.mjs --scope project --project-dir <프로젝트>`.

목록을 바꾸려면 `settings/claude-settings.json` 을 고쳐 push 하고, 각 머신에서 `git pull` 후 `apply-settings.mjs` 를 다시 실행한다.
도구를 없앨 때는 목록에서 지우고 `retired` 에 추가해야 이미 설치한 머신에서도 정리된다.

## 업데이트가 따라가는 방식
- **공식·원본 마켓플레이스 플러그인**: 각 마켓플레이스가 갱신되면 자동 업데이트로 따라간다. 버전 규칙은 각 원본의 것을 따른다
  (원본 `plugin.json` 에 `version` 이 있으면 원본이 그 값을 올릴 때 업데이트된다).
- **이 마켓플레이스의 플러그인**: `.github/workflows/sync-upstream.yml` 이 매일 06:17 KST 에 `scripts/sync-upstream.mjs` 를 실행해
  각 `source.sha` 를 업스트림 최신 커밋으로 올리고 커밋한다(`git-subdir` 는 해당 폴더를 바꾼 최신 커밋).
  항목에 `version` 을 적지 않으므로 커밋 SHA 가 곧 버전이 되어, 바뀐 플러그인만 업데이트된다.
  - 수동 실행: Actions 탭 "Sync upstream pins" → Run workflow, 또는 `GITHUB_TOKEN=$(gh auth token) node scripts/sync-upstream.mjs --dry-run`.
  - 릴리스 직후 커밋을 바로 받지 않으려면 저장소 변수 `MIN_AGE_DAYS` 를 설정한다(예: 3 → 3일 이상 지난 커밋만 채택).

## 공식 마켓플레이스 플러그인 (`enabledPlugins` 로 켬)
`playwright`, `superpowers` (모두 `@claude-plugins-official`)

- `superpowers` 는 SessionStart 훅이 있다.

## 원본 마켓플레이스 플러그인
모두 기본으로 켬 (`enabledPlugins`):

| 플러그인 ID | 내용 | 원본 |
|---|---|---|
| `taste-skill@taste-skill` | 프런트엔드 디자인 스킬 (`design-taste-frontend`). 회사·마케팅 웹사이트 수준의 규칙과 실제 브라우저 확인 단계가 있다. 매 세션 약 240 토큰, 사용 시 약 7,300 토큰 | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) |

## 이 마켓플레이스의 플러그인
지금은 `kibeen-skills` 플러그인 하나뿐이다. 들어 있는 것:

| 구성 | 종류 | 하는 일 |
|---|---|---|
| `pr-review-loop` | 스킬 | 모든 구현 PR 에, 오래 걸리는 검증이 있으면 그 전에: draft PR → 리뷰 서브에이전트 리뷰·반영(self-approve 까지, 최대 3회) → CI 통과까지 수정 → PoC 평가 결과 코멘트(평가가 없으면 건너뜀) → 사용자가 폐기 판정하면 PR 닫고 브랜치 삭제 |
| `pr-reviewer` | 서브에이전트 | `pr-review-loop` 의 독립 리뷰어. 코드 결함과 PoC 평가 계획을 보고 PR 코멘트로 VERDICT 를 남긴다 |
| 동기화 훅 | SessionStart 훅 | 이 머신을 `settings/` 에 맞춘다(설치·제거·답변 지침) |

매 세션 비용 약 100 토큰.

### 논문·기술 문서 작성 스킬 (기본 켬)
각 원본의 스킬 폴더 하나만 `git-subdir` 로 가리킨다. API 키는 모두 선택이다(없어도 동작, 넣으면 검색 한도가 늘어난다).

| 이름 | 하는 일 | 원본 |
|---|---|---|
| `scientific-writing` | 논문 원고 작성 (IMRAD 구조, 문단 단위 서술, 보고 지침) | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) (MIT) |
| `citation-management` | 인용 관리 (DOI·PubMed·OpenAlex 메타데이터, BibTeX). 선택: `NCBI_API_KEY`, `OPENALEX_API_KEY` | 위와 같음 |
| `literature-review` | 체계적 문헌 조사와 정리. 선택: `OPENROUTER_API_KEY`, PDF 출력은 Pandoc·XeLaTeX | 위와 같음 |
| `peer-review` | 심사위원 관점 원고 검토 | 위와 같음 |
| `venue-templates` | 학회·저널 양식과 제출 요건 | 위와 같음 |
| `paper-lookup` | 논문 검색 (PubMed, arXiv, Semantic Scholar 등). 키 불필요 | 위와 같음 |
| `doc-coauthoring` | 기술 문서·제안서·설계 문서 공동 작성 절차 | [anthropics/skills](https://github.com/anthropics/skills) (Anthropic 공식) |

7개 합계 매 세션 약 820 토큰. 원본에 없는 묶음이 필요해지면 여기에 업스트림 소스와 `sha` 로 추가한다.
`.github/workflows/sync-upstream.yml` 이 그런 항목의 `sha` 를 매일 업스트림 최신으로 올린다.

## 제거한 도구 (`retired`)
역할이 겹쳐 남기지 않은 도구다. `apply-settings.mjs` 가 각 머신에서 정리한다.

| 분야 | 남긴 것 | 제거한 것 |
|---|---|---|
| 개발 방법론 | `superpowers` | `gsd-core`, `systematic-debugging`, `test-driven-development` |
| 프런트엔드 디자인 | `taste-skill` | `frontend-design`, `ui-ux-pro-max`, `impeccable`, `design-skills` |
| 브라우저 제어 | `playwright` | `chrome-devtools-mcp`, `agent-browser` |

k-skill(NomaDamas/k-skill) 에서 가져왔던 55개 스킬도 제거했다.

성능 부담이 커서 제거: `claude-mem`(worker + 훅 9개), `skill-seekers`(Python 패키지가 없으면 매 세션 MCP 연결 실패), 쓰지 않는 서비스 연동 `canva`, `supabase`, `vercel`, `notion`, `firecrawl`, `repomix-mcp`(명령·에이전트가 MCP 없이 동작해 중복), `perplexity`(API 키 필요, 내장 웹 검색으로 대체), `higgsfield`(유료 크레딧 필요). 쓰지 않는 스킬 `canvas-design`, `algorithmic-art`, `tapestry`, `find-skills`, `mcp-builder`, `repomix-commands`, `repomix-explorer`, `hyperframes`(매 세션 약 3,900 토큰, 슬라이드 요청을 가로챔), `caveman`(어색한 압축 말투, 아래 답변 지침으로 대체), `superpowers-lab`(실험 단계, 리눅스·tmux·Docker 필요), `content-research-writer`(블로그용, 보고서·논문 형식에 안 맞음).

## Windows
원본 마켓플레이스는 레포 전체를 받는다. 경로가 깊은 레포는
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
0. 같은 역할의 도구가 이미 있으면 추가하지 않는다(위 "제거한 도구" 표 참고). `claude plugin details <ID>` 로 매 세션 비용을 먼저 본다.
1. 공식 마켓플레이스에 있으면 → `settings/claude-settings.json` 의 `enabledPlugins` 에 `<이름>@claude-plugins-official`.
2. 원본이 자체 마켓플레이스를 제공하면 → `extraKnownMarketplaces` 에 그 레포를 `autoUpdate: true` 로 추가하고, README 표에 플러그인 ID 를 적는다.
3. 둘 다 아니거나 일부만 골라야 하면 → `.claude-plugin/marketplace.json` 에 업스트림 소스와 `sha` 로 추가한다(`version` 은 적지 않는다).
   추가 후 `claude plugin validate .` 로 검사한다.
