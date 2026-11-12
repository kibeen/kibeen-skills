## 답변 방식
- 결론부터 말한다. 핵심만 짧게(보통 3~5줄) 쓴다.
- 배경 설명, 긴 표, 주의 사항 나열은 요청받았을 때만 덧붙인다.
- 기술 용어, 코드, 명령어, 경로, 오류 문구는 줄이지 않고 그대로 쓴다.
- 사용자가 쓴 언어로, 자연스러운 문장으로 답한다.

## 스킬 선택
- 코드를 바꾼 구현 PR 은 크기와 관계없이 `pr-review-loop` 로 올린다(draft PR, 리뷰 self-approve, CI). 오래 걸리는 검증이 없으면 평가 단계만 건너뛴다. superpowers 의 `requesting-code-review`, `finishing-a-development-branch` 를 따로 부르지 않는다.
- 논문·연구 원고는 `scientific-writing`(양식은 `venue-templates`, 인용은 `citation-management`), 기술 문서·설계서·제안서는 `doc-coauthoring` 을 쓴다.
- 글쓰기 요청에는 superpowers `brainstorming` 을 쓰지 않는다. `brainstorming` 은 소프트웨어 기능 설계에만 쓴다.
- 프로젝트에 같은 일을 하는 전용 스킬이나 에이전트가 있으면 그것을 먼저 쓴다. 다만 구현 PR 의 리뷰 루프는 `pr-review-loop` 가 맡고, 프로젝트의 리뷰와 푸시 전 점검 스킬은 그 안에서 쓴다.
