---
name: pr-merge-loop
description: 사용자가 채택(accept)한 PR 을 열어 머지될 때까지 맡을 때 쓰는 절차. pr-review-loop 의 판정이 채택일 때, 또는 "PR 열어줘", "auto-merge 켜줘", "머지까지 봐줘", "CI 통과까지 고쳐줘", "리뷰 코멘트 확인해줘", "PR 이어서 봐줘" 처럼 이미 올라간 PR 의 필수 CI 실패와 리뷰어 코멘트를 처리해 달라는 요청에 쓴다.
---

# PR 머지 루프

목적: 사용자가 채택한 PR 을 ready 로 열고 auto-merge 를 켠 뒤, 머지를 막는 CI 실패와 리뷰어 코멘트를 처리한다.
PR 이 `MERGED` 가 되면 끝난다.

시작 조건은 **사용자가 이 PR 을 채택한다고 답한 것**이다. 평가 결과가 기준을 넘은 것, 리뷰어의 Approve, 사용자의 무응답은
채택이 아니다. 답이 없으면 결과를 보고하고 기다린다.

채택은 이 절차가 하는 일에 대한 허락이다: PR 열기, auto-merge, 수정 커밋 푸시, 진행 코멘트, 리뷰어 답글과 재리뷰 요청.
이 일들은 단계마다 다시 묻지 않고 진행한다. 예외는 둘이다.
- 리뷰 지적을 **반영하지 않겠다는 답**(`안 고침`)은 문안을 사용자에게 보여 승인을 받은 뒤에 올린다(3.2, 3.4).
- 프로젝트 규칙이 따로 허락을 요구하는 동작(예: 릴리스 브랜치 머지)은 채택과 별개로 그 허락을 받는다.

리뷰어 답글에는 확인한 사실과 한 일만 쓴다. 사용자가 정할 것(범위, 설계, 일정)을 대신 약속하지 않는다.

## 상태 읽기와 기록
상태는 감시 스크립트로 읽는다(이 스킬 폴더의 `scripts/pr-merge-watch.mjs`, PR 을 바꾸지 않는다).
아래에서 `필드.이름` 은 이 출력의 JSON 필드다. `hint` 는 지금 상태를 한 줄로 요약한다.
```bash
node "${CLAUDE_SKILL_DIR}/scripts/pr-merge-watch.mjs" status <PR> [--repo owner/name]   # 지금 상태 한 번
node "${CLAUDE_SKILL_DIR}/scripts/pr-merge-watch.mjs" wait <PR> [--repo owner/name]     # 내가 할 일이 생길 때까지 기다림
```

진행 상태는 PR 코멘트 첫 줄의 표시로 남긴다(pr-review-loop 과 같은 형식). `round` 는 그 step 의 순번이고 `markers.next.<step>` 값을 쓴다.
`sha` 는 코멘트를 올리는 시점의 head 다.
`<!-- pr-review-loop step=<open|hold|ci|feedback> round=<N> sha=<head 커밋> -->`

| step | 뜻 | 언제 올리나 |
|---|---|---|
| `open` | 사용자가 채택했다. 마지막 `open` 의 sha 가 채택된 커밋(`markers.acceptedSha`)이다. `mode=auto\|manual\|unreviewed` 를 덧붙인다 | 채택 직후(1단계), 머지 방식을 바꿀 때, 보류가 풀려 다시 진행할 때 |
| `hold` | 사용자 결정을 기다린다. 머지하지 않는다 | 사용자에게 물을 때(2단계의 선택, 3.4). 다음 `open` 이 보류를 닫는다 |
| `ci` | CI 실패를 처리했다 | 3.1 |
| `feedback` | 리뷰어 코멘트를 처리했다. `until=<시각>` 을 덧붙인다. `안 고침` 문안이 사용자 승인을 기다리는 항목은 `ask=<id,...>` 로 적는다 | 3.2 |

새 세션에서 이어받을 때는 `status` 를 한 번 돌린다.
- `markers.hold` 가 있으면 그 코멘트의 질문이 아직 열려 있다. 답이 대화에 없으면 사용자에게 다시 묻는다.
  `markers.reevaluating` 이 true 면(보류 뒤에 `review`, `fix`, `poc` 표시가 있다) 재평가 중이므로 pr-review-loop 으로 이어간다.
- `markers.acceptedSha` 가 있으면 채택된 PR 이다. `markers.mode` 가 `auto` 가 아니거나 `autoMerge.enabled` 가 true 면 3단계부터 한다.
  `mode` 가 `auto` 인데 auto-merge 가 꺼져 있으면 `autoMerge.disabledBy` 를 본다. 없으면 켠 적이 없는 것이니 2단계부터 한다.
  있으면 누군가 끈 것이다. 다시 켜지 않고 사용자에게 보고한다.
- 둘 다 없으면 아직 채택 전이다. pr-review-loop 으로 돌아간다.
- `feedback.awaitingUser` 에 항목이 있으면 `안 고침` 답글 문안이 사용자 승인을 기다리는 중이다. 문안은 PR 에 남아 있지 않으므로
  다시 써서 보여 준다(3.2 의 5번). 마지막 반영 코멘트에 `답하지 않음(사용자 결정)` 으로 적힌 항목은 다시 묻지 않는다.

## 1. 열기
1. `status` 를 돌리고 머지 방식을 정한다. 레포 규칙(레포 `CLAUDE.md`, 기여 문서)에 적힌 방식을 쓰고, 없으면 `repo.defaultMergeMethod` 를 쓴다.
2. open 코멘트를 올려 채택을 기록한다.
   ```
   <!-- pr-review-loop step=open round=<markers.next.open> sha=<head> mode=auto -->
   채택: 사용자 판정. 채택 커밋 <sha>, 머지 방식 <방식>.
   ```
3. PR 본문을 리뷰어가 읽을 최종본으로 고친다(`gh pr edit <PR> --body-file <본문.md>`): 변경 요약, 테스트,
   평가 결과 요약과 결과 코멘트 링크, 평가한 커밋. 프로젝트의 글쓰기 규칙이 있으면 따른다.
4. draft 면 `gh pr ready <PR>`.
5. `status` 를 다시 돌려 `autoMerge.effect` 를 본다.

## 2. auto-merge 켜기

auto-merge 는 base 브랜치가 **필수로 정한** 리뷰와 체크만 기다린다. 필수가 아닌 것은 기다리지 않고 머지하므로,
켜기 전에 무엇을 기다릴지 `autoMerge.effect` 로 확인한다(사유는 `autoMerge.note`). auto-merge 가 이미 켜져 있어도
판정은 같다. `no_review`, `not_enforced`, `ci_not_run`, `ci_not_green` 이면 먼저 끄고(`gh pr merge <PR> --disable-auto`) 그 행을 따른다.

| `autoMerge.effect` | 뜻 | 할 일 |
|---|---|---|
| `arms` | 리뷰와 필수 체크를 기다렸다가 머지된다 | `gh pr merge <PR> --auto --<방식>` |
| `merges_now` | 사람이 승인했고 체크도 다 찼다. 켜는 순간 머지된다 | 같은 명령. 규칙이 허용하고 사용자가 채택한 머지다 |
| `no_review` | base 가 리뷰를 요구하지 않고 이 커밋을 승인한 사람도 없다. `--auto` 는 **리뷰 없이** 머지한다(지금 바로, 또는 필수 체크가 통과하는 즉시) | 실행하지 않는다. hold 코멘트를 올리고 묻는다(지금 CI 상태도 함께): 리뷰 없이 머지 / 리뷰 승인 뒤 머지 |
| `not_enforced` | base 가 리뷰나 CI 중 하나를 필수로 걸지 않았다. auto-merge 는 그것을 기다리지 않는다(승인만으로 CI 없이, 또는 푸시로 승인이 낡아도 그대로 머지) | 켜지 않는다. `mode=manual` 인 open 코멘트를 올리고 3단계로 간다. 사용자에게 승인과 CI 통과 뒤 직접 머지한다고 알린다 |
| `ci_not_run` | 필수 체크가 한 번도 실행되지 않고 skip 됐다(`checks.skipped`). GitHub 는 이것을 통과로 친다 | 레포의 CI 실행 규칙(라벨, 수동 실행)대로 CI 를 먼저 돌리고 `status` 를 다시 본다. 그 skip 이 레포에서 정상(경로 필터 등)이면 `--skip-ok=<체크 이름,...>` 을 붙인다 |
| `ci_not_green` | GitHub 는 머지 가능으로 보지만 실행된 체크 중 통과하지 못한 것이 있다(예: 실패한 필수 체크를 뒤의 skip 된 실행이 덮음). `--auto` 는 그대로 머지한다 | 켜지 않는다. 3.1 로 CI 를 먼저 통과시키고 `status` 를 다시 본다 |
| `not_allowed` | 저장소가 auto-merge 를 꺼 두었다 | hold 코멘트를 올리고 묻는다: 승인과 CI 뒤 내가 머지 / 그대로 둠 |
| `enabled` | 이미 켜져 있고 리뷰와 필수 체크를 기다린다 | `autoMerge.method` 가 맞는지만 확인 |
| `unknown` | GitHub 가 아직 계산 중이다 | `status` 를 다시 돌린다 |

`draft` 가 나오면 1단계의 `gh pr ready` 가 안 된 것이고, `closed` 면 PR 이 닫힌 것이다.

hold 코멘트는 질문을 한 줄로 적는다.
```
<!-- pr-review-loop step=hold round=<markers.next.hold> sha=<head> -->
보류: <무엇을 정해야 하는지>. 사용자 결정 대기.
```
사용자의 답에 따라 open 코멘트를 올려 보류를 닫고 3단계로 간다.
- **리뷰 없이 머지**: `mode=unreviewed`. 모든 체크가 통과하면 `ready` 가 오고 그때 내가 머지한다. 실패한 CI 를 둔 채 머지하지 않는다.
- **승인 뒤 머지**(`no_review`), **승인과 CI 뒤 내가 머지**(`not_allowed`): `mode=manual`.
- **그대로 둠**: open 코멘트 없이 보류를 둔 채 보고하고 끝낸다.

`mode=manual` 과 `mode=unreviewed` 에서는 auto-merge 를 켜지 않고 내가 유일한 관문이 된다. `manual` 의 `ready` 는 사람이
**지금 head 를** 승인했고(`review.approvals`), 변경 요청이 없고, 모든 체크가 통과했을 때만 온다. 이전 커밋의 승인
(`review.staleApprovals`)과 봇의 승인은 치지 않는다. `unreviewed` 의 `ready` 는 승인 없이 체크 통과만 본다.

리뷰할 사람이 없으면(`review.requested` 가 비었고 `review.approvals` 도 비었다) 사용자에게 알린다.
리뷰어를 정해 주면 `gh pr edit <PR> --add-reviewer <login>`.

## 3. 감시 루프
`wait` 를 **백그라운드로** 띄운다(Bash 의 `run_in_background`). 내가 할 일이 생기면 스크립트가 끝나고 하네스가 다시 불러 준다.
그동안 폴링하거나 sleep 하지 않는다. 띄울 때 무엇을 기다리는지 사용자에게 한 줄로 알린다(`hint`).
기본은 시간 제한이 없다. 백그라운드 실행이 없는 환경이면 `--timeout 9m` 을 붙여 반복한다.
세션이 끝나면 감시도 끝난다. 다음 세션이 `status` 로 이어받는다.

끝나면 출력의 `event`(깨운 이유)와 `also`(함께 열려 있는 이벤트)를 모두 처리하고 다시 `wait` 를 띄운다.
수정 커밋을 푸시할 때마다 레포의 CI 실행 규칙을 다시 적용한다(라벨로 CI 를 돌리는 레포는 라벨을 다시 붙인다).

| `event` | 할 일 |
|---|---|
| `merged` | 4단계 |
| `ci_failed` | 3.1 |
| `feedback` | 3.2 |
| `behind`, `conflict` | 3.3 |
| `hold` | 사용자 결정을 기다리는 보류가 열려 있다. `autoMerge.enabled` 가 true 면 먼저 끈다. 답을 받기 전에는 `wait` 를 다시 띄우지 않는다 |
| `ci_not_started` | `checks.missingRequired`(보고되지 않음)나 `checks.skipped`(skip 만 됨)의 필수 체크가 돌지 않았다. 레포의 CI 실행 규칙대로 돌린다. 그 skip 이 레포에서 정상이면 `--skip-ok=<체크 이름,...>` 을 붙여 다시 `wait`. 규칙을 모르면 보고한다 |
| `ready` | (`mode=manual`, `unreviewed`) 머지 조건이 찼다. `gh pr merge <PR> --<방식>`. 머지가 실패하면 다시 `wait` 하지 않고 오류를 보고한다 |
| `auto_merge_off` | `autoMerge.disabledBy` 가 있으면 누군가 끈 것이다. 다시 켜지 않고 보고한다. 없으면 켠 적이 없는 것이니 2단계를 한다 |
| `auto_merge_unsafe` | auto-merge 가 켜져 있는데 리뷰나 CI 를 기다려 주지 않는 상태가 됐다(예: 푸시로 승인이 낡음). 먼저 끄고 2단계의 표를 다시 따른다 |
| `stuck` | 승인과 체크가 찼는데 머지되지 않는다. `pr.mergeStateStatus`, `review.unresolvedThreads`, `rules` 로 원인을 찾고, 못 찾으면 보고한다 |
| `closed` | 머지 없이 닫혔다. 보고하고 끝낸다 |
| `draft` | `markers.acceptedSha` 가 없으면 1단계가 끝나지 않은 것이다. 있으면 누군가 draft 로 되돌린 것이다. `gh pr ready` 를 다시 하지 않고 보고한다 |
| `timeout` | 다시 `wait` |
| `error` | 스크립트가 PR 을 읽지 못했다. `hint` 의 사유(gh 로그인, PR 번호, 네트워크)를 확인한다 |

`status` 의 `event` 가 `waiting` 이면 지금 할 일이 없다는 뜻이다.
표시는 `gh` 계정 본인이나 PR 작성자가 올린 코멘트의 것만 읽는다. 남이 쓴 표시는 채택이나 처리 기록으로 치지 않는다.

### 3.1 CI 실패
1. 로그를 본다: `gh run view <checks.failed[].runId> --log-failed | tail -200`. runId 가 없으면 `url` 을 연다.
2. 원인이 이 PR 의 변경이면 고치고 커밋·푸시한다.
3. 이 PR 과 무관하면(인프라, flaky, base 에서도 같은 실패) 코드를 건드리지 않는다. base 의 같은 체크 이력에서 같은 실패를 확인하고
   (`gh run list --branch <base> --workflow <워크플로> --limit 10`, 실패한 실행은 `gh run view <id> --log-failed`),
   실패한 잡만 한 번 다시 돌린다(`gh run rerun <runId> --failed`). 다시 실패하면 근거를 붙여 보고한다.
4. 어느 쪽이든 CI 코멘트(step=ci)를 올린다: 실패한 체크 이름, 원인, 고친 커밋 또는 재실행한 근거. 이 기록으로 횟수를 센다.
5. 고쳐서 푸시했는데도 같은 체크가 세 번 이어서 실패하면 멈추고 보고한다.

고치는 대상은 결함이다. 체크를 통과시키려고 테스트를 skip 하거나 지우거나 기대값을 실패에 맞추지 않는다.
`--admin` 머지와 필수 체크 해제도 하지 않는다.

### 3.2 리뷰어 코멘트
`feedback.items` 를 하나씩 본다(`kind`: `review` 리뷰 본문, `thread` 인라인 스레드, `comment` 대화 코멘트).
지적이 맞는지는 코드로 확인한 뒤에 판단한다.

| 판단 | 할 일 |
|---|---|
| 맞는 지적이고 평가가 잰 동작을 바꾸지 않는다 | 고친다 |
| 질문이다 | 코드를 근거로 답한다 |
| 반영하지 않는 것이 맞다(`안 고침`) | 기술적 근거를 적은 답글 문안을 쓰되 **올리지 않는다**. 사용자가 승인한 뒤에 올린다(5번) |
| 평가가 잰 동작을 바꾼다, 범위나 설계를 바꾼다, 사용자의 결정과 부딪힌다 | 고치지 않고 3.4 로 간다 |

요청된 변경을 전부든 일부든 하지 않은 채 두는 답은 형식이 무엇이든 `안 고침` 이다. 질문처럼 쓴 요청("왜 dict 를 안 쓰나요?")에
"바꾸지 않는다"고 답하는 것도 같다. 한 항목의 요청 중 일부만 고쳤으면 나머지는 `안 고침` 으로 묻는다. 그 항목이 `thread` 면 답글 전체를 미룬다(내 답글이 달리면
감시가 그 스레드를 끝난 것으로 본다). 반영 코멘트에는 `일부 고침 → <커밋>, 나머지 사용자 확인 중` 으로 적고 `ask` 에 넣은 뒤,
승인을 받으면 고친 것과 승인된 문안을 한 답글로 올린다.
요청이 동작을 바꾸더라도 반영하지 않는 것이 맞다고 판단하면 `안 고침` 이다. 3.4 는 반영할 수도 있어 사용자가 정해야 하는 항목에 쓴다.
본문이 없는 `review` 는 인라인 스레드를 실어 온 것이다. 따로 답하지 않고 `until` 로 닫는다.
답글은 리뷰어가 쓴 언어로 쓴다. 아래의 `고침 →` 같은 표기는 반영 코멘트의 형식이고, 답글에서는 같은 내용을 문장으로 써도 된다.

순서(3.4 로 가는 항목이 있으면 3.4 의 1 과 2 를 먼저 한다):
1. 고칠 것을 고치고 테스트한 뒤 커밋·푸시한다.
2. `thread` 마다 답글을 단다(`고침 → <커밋>`, 답, 3.4 로 간 항목은 사실만: 측정은 현재 값 기준이고 변경 여부를 확인 중).
   `안 고침` 으로 판단한 스레드에는 아직 달지 않는다. 내 답글이 마지막인 스레드는 다음 감시에서 처리된 것으로 본다.
   ```bash
   gh api graphql -f query='mutation($t:ID!,$b:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$t,body:$b}){comment{url}}}' -f t=<threadId> -f b="<답글>"
   ```
3. 반영 코멘트를 올린다. 표시의 `until` 에 `feedback.until` 을 그대로 넣는다(null 이면 뺀다). 그 시각까지의 리뷰 본문과
   대화 코멘트를 처리했다는 기록이고, 빠지면 같은 항목이 다음 감시에서 다시 온다.
   `ask` 에는 문안 승인을 기다리는 항목의 `id` 를 공백과 따옴표 없이 쉼표로 이어 적는다: 이번에 `안 고침` 으로 판단한 `feedback.items[].id` 와
   `feedback.awaitingUser[].id` 전부(답하지 않기로 한 스레드 포함, 그 `답하지 않음(사용자 결정)` 줄도 새 코멘트에 옮겨 적는다).
   없으면 `ask` 를 뺀다. 감시는 **마지막** 반영 코멘트의 `ask` 만 읽는다
   (`until` 은 모든 반영 코멘트 중 가장 늦은 값을 쓰므로 뒤의 코멘트에서 빠져도 앞의 기록은 남는다).
   ```
   <!-- pr-review-loop step=feedback round=<markers.next.feedback> sha=<head> until=<feedback.until> ask=<id,...> -->
   - <리뷰어> <항목>: 고침 → <커밋> | 답함 | 안 고침 → <이유> | 사용자 확인 중
   ```
   `안 고침 → <이유>` 줄에는 사용자가 승인한 문안만 적는다. 승인 전의 항목은 `사용자 확인 중` 으로 적는다.
4. 재리뷰를 요청한다(`gh pr edit <PR> --add-reviewer <login>`). 대상은 `review.changesRequested`, `review.dismissed`
   (푸시로 승인이 취소된 리뷰어), `mode=manual` 이면 `review.staleApprovals`(이전 커밋을 승인한 리뷰어) 중
   `review.requested` 에 없는 사람이다. 그 리뷰어의 항목에 `사용자 확인 중` 이 남아 있으면 결정이 난 뒤에 요청한다.

5. `안 고침` 항목이 있으면 사용자에게 문안을 보여 묻는다. 항목마다 리뷰어와 링크(`url`), 지적 요약, 반영하지 않는 근거,
   **올릴 문안 그대로**를 적는다. 묻고 나서도 `wait` 는 다시 띄운다. `ask` 에 적힌 항목은 `feedback.awaitingUser` 로 옮겨져
   리뷰어가 덧붙이기 전에는 다시 깨우지 않는다. auto-merge 는 끄지 않는다. 그 리뷰어가 답을 기다리지 않고 승인하면 그 항목은 끝난 것으로 본다.
   답을 받으면 올리기 전에 `status` 로 그 항목이 아직 `feedback.awaitingUser` 에 있는지 본다. `feedback.items` 로 돌아와 있으면
   리뷰어가 덧붙인 것이니 다시 판단한다. 어디에도 없으면 그 사이 상태가 바뀐 것이다(리뷰어가 승인했거나 스레드를 resolve 했거나
   리뷰가 dismiss 됐거나 누군가 직접 답했다). 올리지 않고 원인을 확인해 사용자에게 알린다.
   - **승인**(사용자가 고친 문안 포함): `thread` 는 그 문안을 답글로 올리면 풀린다. `review` 와 `comment` 는 `ask` 에서 그 `id` 를 빼고
     `안 고침 → <승인된 문안 그대로>` 줄을 적은 반영 코멘트를 새로 올려야 풀린다. 그 뒤 4번을 한다.
     `wait` 가 이미 돌고 있으면 그대로 둔다.
   - **고쳐라**: 그 항목으로 1-4번을 다시 한다(동작을 바꾸면 3.4). 새 반영 코멘트의 `ask` 에서 그 `id` 를 뺀다.
   - **답하지 않음**: 새 반영 코멘트에 `답하지 않음(사용자 결정)` 줄로 남긴다. `review` 와 `comment` 는 `ask` 에서 빼면 끝난다.
     `thread` 는 `ask` 에 둔 채(빼면 다시 깨운다) 4번을 한다. 일부를 고친 스레드였으면 고친 부분만 답글로 올린다(거절이 없는 답이고
     스레드도 닫힌다). 이 스레드는 `feedback.awaitingUser` 에 계속 보이지만 다시 묻지 않는다.
     `rules.threadResolutionRequired` 가 true 면 누군가 resolve 하기 전에는 머지되지 않는다고 그 자리에서 사용자에게 알린다.
   - 답이 없으면 올리지 않는다. 무응답은 승인이 아니다.

   이렇게 뒤따라 올리는 반영 코멘트에는, 그 시점의 `feedback.items` 까지 1-4번으로 처리했을 때만 `until` 을 넣는다.
   처리하지 않은 항목이 있는데 `until` 을 넣으면 그 항목이 기록에 덮여 사라진다.

승인은 사람이 한다. 스스로 approve 하거나 남의 리뷰를 dismiss 하지 않는다. 스레드 resolve 는 리뷰어에게 맡긴다.
`rules.threadResolutionRequired` 가 true 이고 그 리뷰어가 승인한 뒤라면, 고치고 답글을 단 스레드만 resolve 한다.
`gh api graphql -f query='mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}' -f t=<threadId>`

### 3.3 base 와 어긋남
- `behind`: `gh pr update-branch <PR>` (base 를 merge 한다). rebase 와 force-push 는 리뷰 기록을 깨므로 쓰지 않는다.
- `conflict`: 로컬에서 base 를 merge 해 충돌을 풀고, 테스트한 뒤 푸시한다. 충돌 해소가 평가가 잰 코드에 닿으면 3.4 로 간다.

### 3.4 채택 뒤 코드 변경의 한계
사용자가 채택한 것은 `markers.acceptedSha` 의 동작이다. 그 뒤의 수정(CI 수정, 리뷰 반영, 충돌 해소)이 평가가 잰 동작을 바꾸면
채택의 근거가 사라진다.

- 동작을 바꾸지 않는 수정(테스트, lint, 타입, 주석과 문서, 이름 변경, 측정 경로 밖의 코드)은 그대로 진행한다.
- 동작을 바꾸는 수정(알고리즘, 기본값과 설정, 측정 경로의 분기)이 필요하거나 요청되면 아래 순서로 멈춘다.
- 어느 쪽인지 애매하면 `git diff <acceptedSha>..HEAD` 로 확인하고, 그래도 애매하면 바꾸는 쪽으로 본다.

멈추는 순서:
1. auto-merge 가 켜져 있으면 먼저 끈다: `gh pr merge <PR> --disable-auto`. 켜 둔 채 물으면 답이 오기 전에 승인만으로 머지된다.
2. hold 코멘트를 올린다(형식은 2단계와 같다). 리뷰 스레드에서 나온 질문이면 그 `threadId` 를 본문에 적어 둔다.
3. 사용자에게 묻는다: 바꾸지 않음 / 반영하고 재평가 / 후속 PR. 리뷰어의 요청에서 나온 것이면 바꾸지 않음과 후속 PR 을 골랐을 때
   리뷰어에게 올릴 답글 문안도 그대로 함께 보인다. 이 답글도 `안 고침` 이다.
4. 답에 따라:
   - **바꾸지 않음, 후속 PR**: 선택만 받고 문안 승인을 못 받았으면 문안을 다시 보여 승인받는다. 그때까지 보류를 닫지 않는다
     (open 코멘트도 auto-merge 도 없다). 승인된 문안 그대로 해당 스레드에 답한 뒤에 2단계 표대로 auto-merge 를 다시 켠다.
     open 코멘트(`sha=<지금 head>`, 본문은 `재개: <결정>`)를 올려 보류를 닫고, 3.2 의 4번을 한 뒤 3단계로 돌아간다.
   - **반영하고 재평가**: 먼저 `평가 무효: 커밋 <옛 평가 커밋>, 사용자 지시 재평가.` 코멘트(step=poc)를 올리고 pr-review-loop 2단계부터
     다시 한다(수정, 리뷰, CI 와 평가, 채택 판정). 리뷰 라운드 상한은 새로 3회다. 다시 채택되면 1단계부터 한다.

## 4. 끝
`merged` 이벤트가 오거나 직접 머지가 성공하면 사용자에게 보고하고 끝낸다: 머지 커밋(`pr.mergeCommit`), 채택 커밋 뒤에
추가된 커밋, 처리한 CI 실패와 리뷰 반영. `feedback.awaitingUser` 가 남아 있으면 보고에 넣고, 사용자가 승인한 문안은 머지 뒤에도 올린다.
로컬 브랜치와 워크트리를 정리한다(squash 머지 뒤에는 `git branch -D`).
원격 브랜치는 저장소의 자동 삭제 설정에 맡긴다.

## 멈추고 사용자에게 보고할 때
`no_review` 와 `not_allowed` 의 선택, 3.4 의 동작 변경, 같은 체크의 3회 실패, PR 과 무관한 실패의 재실패,
남이 끈 `auto_merge_off`, 남이 되돌린 `draft`, 직접 머지의 실패, 원인을 못 찾은 `stuck`, `closed`.
보고에는 PR 링크, 지금 상태(`hint`), 선택지를 넣는다.
3.2 의 `안 고침` 문안은 사용자에게 묻되 감시는 멈추지 않는다.
