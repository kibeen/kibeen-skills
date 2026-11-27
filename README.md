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
- 이 방식은 설치만 한다. 다른 플러그인을 지우거나 끄는 것은 아래 `apply_settings.py` 로 한다.
- `kibeen-skills` 플러그인 의 SessionStart 훅이 이 레포에 새 커밋이 있을 때, 아니면 하루 한 번 이 머신을 설정에 맞춘다.
  설치·켜기·제거를 모두 자동 적용하고(설정 백업 생성), 무엇을 했는지 한 줄 알림을 띄운다. 모델 컨텍스트에는 넣지 않는다.
  새로 켠 플러그인은 다음 세션부터 쓸 수 있다.
- 자동 적용 대신 알림만 받으려면 환경변수 `KIBEEN_AUTO_APPLY=0`. 수동 확인은
  `python ~/.claude/plugins/marketplaces/kibeen-skills/scripts/apply_settings.py --dry-run`.
- 제거 목록(`retired`)에 있는 도구는 그 머신에서 직접 다시 설치해도 다음 동기화 때 다시 제거된다.

## 지침과 출력 스타일 (모든 머신에 자동 적용)
답변을 짧게 쓰게 하는 일은 Claude Code 내장 출력 스타일 `Concise` 가 맡는다. `settings/claude-settings.json` 의
`outputStyle` 을 `apply_settings.py` 가 각 머신의 `settings.json` 에 넣는다. 그 머신에서 다른 스타일을 골라 두었어도 `Concise` 로 맞춘다
(데스크톱 앱 Code 탭의 출력 스타일 설정도 이 값이다). 그 머신의 선택을 유지하려면 환경변수 `KIBEEN_KEEP_OUTPUT_STYLE=1`.
`Concise` 는 Claude Code 2.1.237 이상에서 동작하고, 그보다 낮은 버전은 기본 스타일로 돈다.

`settings/CLAUDE.kibeen.md` 의 지침(스킬 선택 규칙, 진행과 결과 보고에서 지엽적인 정보는 빼고 이해에 필요한 맥락은 주는 보고 규칙, 스스로 지은 이름과 읽는 사람이 모르는 용어를 풀어 쓰는 용어 규칙)을 `apply_settings.py` 가 각 머신의 `~/.claude/CLAUDE.md` 에 관리 블록
(`<!-- BEGIN kibeen-skills ... -->` ~ `<!-- END kibeen-skills -->`)으로 넣는다. 블록 밖 내용은 건드리지 않고, 바꾸기 전에 백업한다.
`kibeen-skills` 플러그인 훅이 자동 동기화하므로 이 파일을 고쳐 push 하면 모든 머신에 반영된다. 파일을 지우면 블록도 지워진다.

### 보고 규칙의 효과 측정
보고와 용어 규칙이 효과가 있는지는 사용자가 답을 되물은 횟수로 잰다. `scripts/count_clarifications.py` 가 그 머신의 대화 기록
(`~/.claude/projects/*/*.jsonl`)에서 사용자가 직접 친 메시지 가운데 "이해가 안", "뭔말인지" 처럼 답을 못 알아들었다는 말(`confused`)과
"X가 뭐야", "무슨 뜻" 처럼 용어를 묻는 말(`asks`)을 날짜별로 세고, 그날 메시지 수에 대한 비율을 낸다.
도구 결과, 클라이언트와 하네스가 붙인 블록(`<` 로 시작하는 IDE 의 열린 파일 알림, 명령과 훅 출력), 서브에이전트 대화, `/compact` 요약, 자동화가 보낸 프롬프트,
500자보다 긴 메시지(대개 붙여 넣은 문서)는 세지 않는다. `asks` 는 "다음 작업은 뭐야?" 같은 질문도 잡으므로
한 번의 값보다 규칙을 바꾸기 전과 바꾼 뒤의 추세를 본다. 사람이 쓰는 머신마다 돌려 합친다(`--json`).
Claude Code 는 `cleanupPeriodDays`(기본 30일)가 지난 대화 기록을 지우므로, 규칙을 바꾸기 전 기간의 `--json` 결과는 그때 저장해 둔다. 나중에는 다시 셀 수 없다.
```bash
python scripts/count_clarifications.py --days 30                            # 오늘까지 30일, 날짜별 표
python scripts/count_clarifications.py --days 7 --until 2026-12-04 --show   # 그날까지 7일, 잡힌 메시지까지
python scripts/count_clarifications.py --days 30 --json > before.json       # 바꾸기 전 기준값 저장
```

## 새 머신 설정 (1회)

요구사항은 **Python 3.11+ (표준 라이브러리만)** 과 `claude` CLI 뿐이다. 이 레포의 스크립트와 훅은 Node.js 를 쓰지 않는다.
다만 기본으로 켜는 `playwright` 플러그인은 MCP 서버를 `npx` 로 띄우므로, 브라우저 제어를 쓰려면 그 머신에 Node.js 가 있어야 한다.

하한은 `scripts/_runtime.py` 의 `MIN_PYTHON` 한 곳에만 적혀 있고, 다른 곳에 더 낮은 버전이 적히면 테스트가 실패한다. CI 도 이 값을 읽어서 쓴다 — 하한과 최신 파이썬을 Linux 와 Windows 양쪽에서 돌리므로, 하한을 올리면 워크플로를 고치지 않아도 그 버전이 그대로 검증된다.

훅은 하한을 만족하는 인터프리터를 스스로 찾는다 — 지금 돌고 있는 것이 낮으면 `python3.13`, `py -3` 등을 차례로 시도한다. 머신에 만족하는 것이 하나도 없으면 동기화를 건너뛰고 설치 명령을 한 줄로 알려 준다(Windows `winget`, macOS `brew`, Linux 는 패키지 관리자 감지). **설치는 직접 하지 않는다** — 런타임 설치는 시스템 변경이고 대개 관리자 권한이 필요해 사용자의 결정으로 남긴다. 조용히 실패하지 않는다. 동기화가 예외로 죽은 경우에도 traceback 을 `~/.claude/plugins/data/kibeen-skills/last-error.log` 에 남기고 사용자에게 알린다 — 세션은 그대로 진행된다.
그 전에 훅 스크립트를 띄울 파이썬은 `hooks.json` 이 `python`, `python3`, `py -3` 순서로 시도한다. `python` 이 없는 환경은 `python3` 가,
Windows 에서 두 이름이 모두 Microsoft Store 스텁(`%LOCALAPPDATA%\Microsoft\WindowsApps`, 종료 코드 49 로 아무것도 하지 않음)으로 잡히는 환경은 Python 런처 `py -3` 가 받는다.
아래 명령을 직접 실행할 때도 같은 순서로 바꿔 쓴다(Windows 에서는 대개 `py -3`).

```bash
git clone https://github.com/kibeen/kibeen-skills.git ~/kibeen-skills
python ~/kibeen-skills/scripts/apply_settings.py --dry-run   # 바뀔 내용 확인
python ~/kibeen-skills/scripts/apply_settings.py             # 적용 (settings.json 백업 생성)
```
Windows 에서 홈 경로가 길면 먼저 `git config --global core.longpaths true` 를 실행한다(아래 "Windows" 참고).

`apply_settings.py` 가 하는 일:

1. **정리** (`claude` CLI 사용): `settings/claude-settings.json` 의 `retired` 에 적힌 마켓플레이스를 제거(그 플러그인도 함께 제거)하고
   플러그인을 제거한다. 이 마켓플레이스에서 빠진 `@kibeen-skills` 플러그인도 제거한다.
2. **병합**: `extraKnownMarketplaces` 를 `autoUpdate: true` 로 선언하고, `enabledPlugins` 의 플러그인을 켠다.
   설치되지 않은 플러그인은 다음 Claude Code 시작 때 자동으로 받는다. 그 머신에서 `false` 로 꺼 둔 플러그인은 다시 켜지 않는다.
   이 마켓플레이스에서 빠진 플러그인의 `enabledPlugins` 항목은 지우고, `outputStyle` 은 저장소 값으로 맞춘다(`KIBEEN_KEEP_OUTPUT_STYLE=1` 이면 그 머신의 값을 둔다).
   플러그인과 출력 스타일은 두고 정리와 마켓플레이스 선언만 하려면 `--marketplaces-only`.

**프로젝트 범위**: 한 프로젝트에만 적용하려면 그 프로젝트 폴더에서 `claude plugin install kibeen-skills@kibeen-skills --scope project`.
동기화 훅이 이를 알아보고 `<프로젝트>/.claude/settings.json` 과 `<프로젝트>/.claude/CLAUDE.md` 만 바꾼다(사용자 설정은 그대로).
프로젝트 설정은 커밋해 함께 쓰므로, 출력 스타일은 값이 없을 때만 채우고 이미 정한 값은 바꾸지 않는다.
프로젝트 설정의 플러그인은 시작할 때 자동으로 받아지지 않으므로, 스크립트가 `--scope project` 로 직접 추가·설치한다.
수동 실행: `python scripts/apply_settings.py --scope project --project-dir <프로젝트>`.

목록을 바꾸려면 `settings/claude-settings.json` 을 고쳐 push 하고, 각 머신에서 `git pull` 후 `apply_settings.py` 를 다시 실행한다.
도구를 없앨 때는 목록에서 지우고 `retired` 에 추가해야 이미 설치한 머신에서도 정리된다.

## 업데이트가 따라가는 방식
- **공식·원본 마켓플레이스 플러그인**: 각 마켓플레이스가 갱신되면 자동 업데이트로 따라간다. 버전 규칙은 각 원본의 것을 따른다
  (원본 `plugin.json` 에 `version` 이 있으면 원본이 그 값을 올릴 때 업데이트된다).
- **이 마켓플레이스의 플러그인**: `.github/workflows/sync-upstream.yml` 이 매일 06:17 KST 에 `scripts/sync_upstream.py` 를 실행해
  각 `source.sha` 를 업스트림 최신 커밋으로 올리고 커밋한다(`git-subdir` 는 해당 폴더를 바꾼 최신 커밋).
  항목에 `version` 을 적지 않으므로 커밋 SHA 가 곧 버전이 되어, 바뀐 플러그인만 업데이트된다.
  - 수동 실행: Actions 탭 "Sync upstream pins" → Run workflow, 또는 `GITHUB_TOKEN=$(gh auth token) python scripts/sync_upstream.py --dry-run`.
  - 릴리스 직후 커밋을 바로 받지 않으려면 저장소 변수 `MIN_AGE_DAYS` 를 설정한다(예: 3 → 3일 이상 지난 커밋만 채택). 0 이상의 숫자가 아니면(예: `3d`) 아무것도 조회하지 않고 실패한다.

## 공식 마켓플레이스 플러그인 (`enabledPlugins` 로 켬)
`playwright`, `superpowers` (모두 `@claude-plugins-official`)

- `superpowers` 는 SessionStart 훅이 있다.

## 원본 마켓플레이스 플러그인
모두 기본으로 켬 (`enabledPlugins`):

| 플러그인 ID | 내용 | 원본 |
|---|---|---|
| `taste-skill@taste-skill` | 프런트엔드 디자인 스킬 (`design-taste-frontend`). 회사·마케팅 웹사이트 수준의 규칙과 실제 브라우저 확인 단계가 있다. 매 세션 약 240 토큰, 사용 시 약 7,300 토큰 | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) |

## 이 마켓플레이스의 플러그인
| 플러그인 | 내용 | 원본 |
|---|---|---|
| `kibeen-skills` | 내용 없는 묶음. `dependencies` 로 기본 도구를 함께 설치하고, SessionStart 훅이 이 머신을 `settings/` 에 맞춘다(설치, 제거, 지침, 출력 스타일) | 이 레포 `plugins/kibeen-skills` |
| `seekflow` | 설계부터 머지까지 결정마다 근거를 요구하는 절차(예전 이름 `pr-loop`). 설계 전 선행 조사 스킬 `prior-art-research`(대표 시스템의 설계와 관련 논문을 조사해 비교 평가), 그 스킬을 superpowers `brainstorming` 이 로드될 때 쓰게 하는 훅, 구현 PR 스킬 `pr-review-loop`, `pr-merge-loop`, 서브에이전트 `pr-reviewer`, 감시 스크립트 `pr_merge_watch.py` | [kibeen/seekflow](https://github.com/kibeen/seekflow) |

`seekflow` 도 다른 항목처럼 HTTPS `url` 소스와 `sha` 로 고정한다. 그 레포에 푸시한 커밋은 다음 `sync-upstream` 실행(위 "업데이트가 따라가는 방식")이
`sha` 를 올린 뒤 자동 업데이트로 각 머신에 들어간다. 바로 받으려면 그 워크플로를 수동으로 돌린다.
전에는 `sha` 없는 `github` 소스였는데, upstream 이 커밋 3개를 더 받는 동안 자동 업데이트가 옛 커밋에 머문 머신이 있었고, Claude Code 가 `github` 플러그인 소스를
SSH 로 받다 실패하면 HTTPS 로 넘어가지 않아 `claude plugin update` 도 GitHub SSH 키가 없는 머신에서 실패했다.

스크립트 테스트: `python -m unittest discover -s tests` (네트워크와 `gh` 없이 돈다. CI 가 PR 마다 Linux/Windows × 하한/최신 네 조합으로 돌리고, 핀을 올리는 `sync-upstream` 은 main 에 푸시하기 전에 스스로 돌린다). 설정 병합과 CLAUDE.md 블록 외에 훅 경로도 덮는다 — 훅 JSON 이 레거시 코드페이지에서도 UTF-8 로 읽히는지, 깨진 `settings.json` 을 덮어쓰지 않는지, `hooks/sync_settings.py` end-to-end, 그리고 `hooks.json` 명령을 Claude Code 가 쓰는 셸(macOS·Linux `sh`, Windows Git Bash)에서 그대로 돌려 Store 스텁을 건너 `py -3` 까지 가는지. 카탈로그의 git 소스가 모두 HTTPS URL 과 `sha` 를 갖는지도 검사한다.

### 기술 문서 작성 스킬 (기본 켬)
원본의 스킬 폴더 하나만 `git-subdir` 로 가리킨다.

| 이름 | 하는 일 | 원본 |
|---|---|---|
| `doc-coauthoring` | 기술 문서, 제안서, 설계 문서 공동 작성 절차 | [anthropics/skills](https://github.com/anthropics/skills) (Anthropic 공식) |

원본에 없는 묶음이 필요해지면 여기에 업스트림 소스(HTTPS URL 의 `url` 또는 `git-subdir`)와 `sha` 로 추가한다.
`.github/workflows/sync-upstream.yml` 이 그런 항목의 `sha` 를 매일 업스트림 최신으로 올린다.

## 제거한 도구 (`retired`)
역할이 겹쳐 남기지 않은 도구다. `apply_settings.py` 가 각 머신에서 정리한다.

| 분야 | 남긴 것 | 제거한 것 |
|---|---|---|
| 개발 방법론 | `superpowers` | `gsd-core`, `systematic-debugging`, `test-driven-development` |
| 프런트엔드 디자인 | `taste-skill` | `frontend-design`, `ui-ux-pro-max`, `impeccable`, `design-skills` |
| 브라우저 제어 | `playwright` | `chrome-devtools-mcp`, `agent-browser` |

k-skill(NomaDamas/k-skill) 에서 가져왔던 55개 스킬도 제거했다.

성능 부담이 커서 제거: `claude-mem`(worker + 훅 9개), `skill-seekers`(Python 패키지가 없으면 매 세션 MCP 연결 실패), 쓰지 않는 서비스 연동 `canva`, `supabase`, `vercel`, `notion`, `firecrawl`, `repomix-mcp`(명령·에이전트가 MCP 없이 동작해 중복), `perplexity`(API 키 필요, 내장 웹 검색으로 대체), `higgsfield`(유료 크레딧 필요). 쓰지 않는 스킬 `canvas-design`, `algorithmic-art`, `tapestry`, `find-skills`, `mcp-builder`, `repomix-commands`, `repomix-explorer`, `hyperframes`(매 세션 약 3,900 토큰, 슬라이드 요청을 가로챔), `caveman`(어색한 압축 말투, 내장 `Concise` 출력 스타일로 대체), `superpowers-lab`(실험 단계, 리눅스·tmux·Docker 필요), `content-research-writer`(블로그용, 보고서·논문 형식에 안 맞음), 논문 작성 스킬 6종 `scientific-writing`, `citation-management`, `literature-review`, `peer-review`, `venue-templates`, `paper-lookup`(쓴 적이 없고 매 세션 약 1,000 토큰).

## Windows
원본 마켓플레이스는 레포 전체를 받는다. 경로가 깊은 레포는
홈 경로가 길면 Windows 경로 길이 제한(260자)에 걸려 `Filename too long` 으로 실패할 수 있다. 먼저 한 번 실행한다.
```
git config --global core.longpaths true
```

`python`, `python3` 가 Microsoft Store 스텁으로 잡히는 머신이 흔하다(`where python` 의 첫 줄이 `...\WindowsApps\python.exe`).
훅은 `py -3` 까지 시도하므로 따로 할 일은 없고, 이 레포의 스크립트를 직접 돌릴 때는 `python` 대신 `py -3` 을 쓴다.
스텁을 없애려면 설정 → 앱 → 고급 앱 설정 → 앱 실행 별칭에서 `python.exe`, `python3.exe` 를 끈다.

훅 명령은 Claude Code 가 Git Bash 로 실행한다. Git Bash 가 없으면 PowerShell 로 실행하는데, Windows PowerShell 5.1 은 `||` 를 모르므로
Git for Windows 를 설치해 둔다.

이 마켓플레이스의 플러그인은 모두 HTTPS URL 로 받으므로 GitHub SSH 키가 없어도 된다.

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
   소스는 HTTPS URL 의 `url`(레포 전체) 또는 `git-subdir`(폴더 하나)로 적는다. `github` 단축형은 SSH 로 받을 수 있어 쓰지 않는다.
   추가 후 `claude plugin validate .` 로 검사한다.
