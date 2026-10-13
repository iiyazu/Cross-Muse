// Minimal self-test for logic.ts hardBreaks. Run: node hooks/logic.selftest.mjs (Node 22.6+ strips types on import).
import { hardBreaks } from './logic.ts'

const cases = [
  ['single newline', 'a\nb', 'a  \nb'],
  ['blank line kept', 'a\n\nb', 'a\n\nb'],
  ['fence untouched', 'x\n```js\nl1\nl2\n```\ny', 'x  \n```js\nl1\nl2\n```\ny'],
  ['table', '| a | b |\n|---|---|\n| 1 | 2 |', '| a | b |  \n|---|---|  \n| 1 | 2 |'],
  ['already hard / trailing newline', 'a  \nb\n', 'a  \nb\n'],
]
let bad = 0
for (const [name, input, want] of cases) {
  const got = hardBreaks(input)
  if (got !== want) { bad++; console.log(`FAIL ${name}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`) }
}
console.log(bad ? 'FAILED' : 'ok')
import { trailingMention, completeMention, foldLong, splitBlocks, mixHex, vendorKey, buildRows, summaryLine, fmtElapsed, zhNotice } from './logic.ts'
const eq = (n, a, b) => { if (JSON.stringify(a) !== JSON.stringify(b)) { bad2++; console.log(`FAIL ${n}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`) } }
let bad2 = 0
eq('mention', trailingMention('hi @op'), 'op'); eq('mention none', trailingMention('hi @op x'), null); eq('mention bare', trailingMention('@'), '')
eq('complete', completeMention('hi @op', 'opencode-2'), 'hi @opencode-2 ')
eq('fold short', foldLong('a\nb'), null)
eq('fold fence', foldLong(Array.from({ length: 20 }, (_, i) => i === 3 ? '```' : 'l' + i).join('\n'), 14, 900, 8)?.text.endsWith('```'), true)
eq('split', splitBlocks('a\n```diff\n+x\n```\nb').map(b => b.kind), ['md', 'diff', 'md'])
eq('mix', mixHex('#000000', '#ffffff', 0.5), '#808080')
eq('vendor', [vendorKey('opencode-2'), vendorKey('x', 'dsh'), vendorKey('agy', 'google'), vendorKey('claude')], ['opencode', 'deepseek', 'google', 'claude'])
const ms = [3, 2, 1].map(i => ({ id: i, from: 'a', thread: '#room', text: 'x', at: 1000 + i }))
eq('group', buildRows(ms).map(r => r.kind), ['group'])
eq('elapsed', fmtElapsed(1000.5, 1000500 + 72000), '1:12')
const zp = zhNotice(`opencode asks permission: shell ['git status -s', "echo \\"failed\\""] — the user decides: run it`)
eq('trace ask', [zp.kind, zp.text, zp.cmds], ['noise', 'opencode 请求执行命令（2 条）', ['git status -s', 'echo "failed"']])
const za = zhNotice('approval per_1 (shell ["sleep 10"]): once, decided by the user via claude sidebar')
eq('trace decided', [za.kind, za.text, za.cmds], ['noise', '已批准一次：执行命令（1 条）', ['sleep 10']])
eq('retracted not grouped', buildRows([{ id: 2, from: 'human', thread: '#room', text: 'x', at: 1002, retracted: true },
  { id: 1, from: 'human', thread: '#room', text: 'y', at: 1001 }]).map(r => r.kind), ['msg', 'msg'])
import { ctxText, ctxLevel, canCompact, mergeCompactInstructions } from './logic.ts'
eq('ctx', [ctxText(0), ctxText(undefined), ctxText(312400), ctxText(400), ctxText(1250000)], ['', '', '312k', '1k', '1.3M'])
eq('ctx level', [ctxLevel(100000), ctxLevel(420000), ctxLevel(500000)], [0, 1, 2])
eq('can compact', [canCompact({ id: 'opencode-1', vendor: 'opencode' }, 'claude-1'), canCompact({ id: 'agy' , vendor: 'agy' }, 'claude-1'),
  canCompact({ id: 'claude-1', vendor: 'claude' }, 'claude-1'), canCompact({ id: 'claude-2', vendor: 'claude' }, 'claude-1')], [true, false, true, false])
eq('merge', [mergeCompactInstructions('', 'H'), mergeCompactInstructions('U', ''), mergeCompactInstructions('U', 'H').startsWith('U\n\n')], ['H', 'U', true])
import { shq, hubStartScript } from './logic.ts'
eq('shq', shq("a'b c"), `'a'\\''b c'`)
const hs = hubStartScript({ python: '/v/bin/python', dir: '/mnt/c/x y', path: '/a:/mnt/c/Program Files/b', init: false })
eq('hub script', [hs.includes(`D='/mnt/c/x y'`), hs.includes(`export PATH='/a:/mnt/c/Program Files/b'`), hs.includes('xmuse init'),
  hs.includes('systemd-run --user'), /U=xmuse-hub-[0-9a-f]+-\$\(date \+%s\)\n/.test(hs)], [true, true, false, true, true])
eq('hub script init', hubStartScript({ python: 'p', dir: '/d', init: true }).includes('"$PY" -m xmuse init "$D"'), true)
import { noiseTone, noiseTitle, ctxBarSvg } from './logic.ts'
eq('tone', [noiseTone([{ id: 1, text: 'opencode 请求执行命令（2 条）' }, { id: 2, text: '已批准一次：执行命令（1 条）' }]),
  noiseTone([{ id: 1, text: '已批准一次：执行命令（1 条）' }]), noiseTone([{ id: 1, text: 'agy 加入 #room' }])], ['ask', 'ok', 'info'])
eq('title', [noiseTitle([{ id: 1, text: 'a' }, { id: 2, text: 'b' }]), noiseTitle([1, 2, 3, 4].map(i => ({ id: i, text: 't' + i })))],
  ['a、b', 't4 等 4 件事'])
eq('bar', [ctxBarSvg(0).includes('#3FB950'), ctxBarSvg(250000).includes('width="28"'), ctxBarSvg(600000).includes('#F85149')], [false, true, true])
import { freshMessage, revealSteps, draftTail } from './logic.ts'
const fv = { timeline: [{ id: 5, from: 'agy', text: 'a' }, { id: 6, from: 'human', text: 'b' }, { id: 7, from: 'opencode', kind: 'done', text: 'c' },
  { id: 8, from: 'opencode', text: 'd' }, { id: 9, from: 'opencode', kind: 'system', text: 'e' }] }
eq('fresh', [freshMessage(fv, 4)?.id, freshMessage(fv, 8), freshMessage(fv, 5)?.id], [8, null, 8])
eq('reveal', [revealSteps(0), revealSteps(10).length, revealSteps(1000).length, revealSteps(120).at(-1)], [[], 3, 10, 120])
eq('tail', [draftTail('short'), draftTail('x'.repeat(300)).length, draftTail('a\n' + 'y'.repeat(300), 200).startsWith('…y')], ['short', 281, true])
import { shortModel } from './logic.ts'
eq('short model', [shortModel('opencode-go/muse-spark-1.3-contributor'), shortModel('sonnet'), shortModel(''), shortModel('a/' + 'x'.repeat(30)).length],
  ['muse-spark-1.3-contribu…', 'sonnet', '', 24])
console.log(bad2 ? 'FAILED' : 'ok2')
