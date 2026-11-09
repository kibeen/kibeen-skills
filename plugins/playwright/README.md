# playwright

Microsoft [Playwright MCP](https://github.com/microsoft/playwright-mcp) 서버를 Claude Code 에 붙이는 플러그인이다.
설치하면 `playwright` MCP 서버가 등록되고, 세션에서 브라우저 탐색, 클릭, 입력, 접근성 스냅샷, 스크린샷 도구를 쓸 수 있다.

- 버전: `@playwright/mcp@0.0.84` 고정. 올리려면 `.mcp.json` 의 버전을 바꾸고 `plugin.json` 의 `version` 을 올린다.
- 필요 조건: Node.js 18 이상과 `npx`. 첫 실행 때 브라우저 바이너리를 내려받는다.
- 이미 `claude mcp add` 로 playwright 를 등록한 머신에서는 도구가 중복되므로 둘 중 하나만 쓴다.

```
/plugin install playwright@kibeen-skills
```
