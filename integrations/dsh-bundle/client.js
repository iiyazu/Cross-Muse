/**
 * xmuse dsh-bundle 侧栏（抽屉）前端：单文件、无 import、无资产，DOM-only。
 * 由宿主经 GET /xmuse/sidebar.js 下发，以 window.__ModuleLoader__.load 注入，
 * 在 dsh 页面右缘画一个可收起的抽屉。令牌只在宿主进程里，这里只有同源 fetch。
 *
 * 内容（XMUSE2-VIEW-API v0 的 /v1/view 快照直渲染）：
 *   成员列表（状态/在线/职责/未读）、时间线（按话题·私聊分组、@我高亮、可加载更早）、
 *   发消息、审批队列（批准一次/总是/拒绝）、对齐条目摘要、开房间/邀请表单（含邀请码与可复制命令）。
 * 刷新：前端长轮询 GET /xmuse/view?since=<version>&wait=25（宿主原样转发 hub /v1/view）。
 */
window.__ModuleLoader__.load({
	id: 'xmuse-sidebar',
	factory: function () {
		var module = { exports: {} };
		var exports = module.exports;

		var ROUTE = '/xmuse';
		var WIDTH = 360;
		var KEY_OPEN = 'xmuse-sidebar:open';
		var KEY_PUSH = 'xmuse-sidebar:push';
		var KEY_THREAD = 'xmuse-sidebar:thread';

		var CSS = [
			':host{all:initial}',
			'*{box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13px}',
			'.tab{position:fixed;top:40%;right:0;z-index:2147483000;writing-mode:vertical-rl;padding:10px 6px;',
			'background:#2b5fd9;color:#fff;border-radius:8px 0 0 8px;cursor:pointer;user-select:none;pointer-events:auto;position:fixed}',
			'.tab[data-alert]{background:#b3261e}',
			'.drawer{position:fixed;top:0;right:0;bottom:0;width:' + WIDTH + 'px;z-index:2147482999;',
			'background:#fff;color:#1b1b1b;border-left:1px solid #ccd;box-shadow:-4px 0 14px rgba(0,0,0,.18);',
			'display:none;flex-direction:column;pointer-events:auto}',
			'.drawer[data-open]{display:flex}',
			'header{display:flex;align-items:center;gap:6px;padding:8px 10px;border-bottom:1px solid #e3e3ee;font-weight:600}',
			'header span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
			'button{border:1px solid #99a;background:#f4f5fb;border-radius:6px;padding:3px 9px;cursor:pointer}',
			'button:disabled{opacity:.5;cursor:default}',
			'button.primary{background:#2b5fd9;border-color:#2b5fd9;color:#fff}',
			'button.danger{border-color:#b3261e;color:#b3261e;background:#fff}',
			'main{flex:1;overflow:auto;padding:8px 10px;display:flex;flex-direction:column;gap:10px}',
			'section{border:1px solid #e3e3ee;border-radius:8px;padding:6px 8px}',
			'section h3{margin:0 0 6px 0;font-size:12px;color:#555;font-weight:600}',
			'.row{display:flex;gap:6px;align-items:center;margin:4px 0}',
			'.row .grow{flex:1;min-width:0}',
			'input[type=text],select{border:1px solid #99a;border-radius:6px;padding:4px 8px;min-width:0}',
			'input[type=text]{flex:1}',
			'.member{display:flex;gap:6px;align-items:baseline;padding:3px 0;border-top:1px solid #f0f0f5}',
			'.member:first-of-type{border-top:none}',
			'.dot{display:inline-block;width:8px;height:8px;border-radius:50%;flex:none;transform:translateY(-1px)}',
			'.st-idle{background:#9aa}.st-running{background:#1a9e54}.st-paused{background:#e08a00}',
			'.st-offline{background:#ccc}.st-queued{background:#2b5fd9}',
			'.desc{color:#555;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
			'.badge{background:#b3261e;color:#fff;border-radius:9px;padding:0 6px;font-size:11px;flex:none}',
			'.badge.gray{background:#888}',
			'.threads{display:flex;flex-wrap:wrap;gap:4px}',
			'.threads button.on{background:#2b5fd9;border-color:#2b5fd9;color:#fff}',
			'.grp{font-weight:600;color:#555;font-size:12px;margin:8px 0 2px 0}',
			'.msg{padding:4px 6px;border-radius:6px;background:#f6f6fa;margin:2px 0;white-space:pre-wrap;word-break:break-word}',
			'.msg[data-me]{background:#fff4d6;border:1px solid #e0c36a}',
			'.meta{color:#777;font-size:11px}',
			'.appr{border:1px solid #e0c36a;border-radius:6px;padding:4px 6px;margin:4px 0;background:#fffdf4}',
			'.align{padding:3px 0;border-top:1px solid #f0f0f5}',
			'.align:first-of-type{border-top:none}',
			'.code{font-family:ui-monospace,Consolas,monospace;background:#f0f0f5;border-radius:4px;padding:1px 5px}',
			'.err{color:#b3261e;white-space:pre-wrap;word-break:break-word}',
			'.dim{color:#777;font-size:12px}',
			'footer{display:flex;gap:6px;padding:8px 10px;border-top:1px solid #e3e3ee}',
		].join('\n');

		function lsGet(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
		function lsSet(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* ignore */ } }
		function el(tag, cls, text) {
			var n = document.createElement(tag);
			if (cls) n.className = cls;
			if (text !== undefined && text !== null) n.textContent = text;
			return n;
		}
		function fmtTime(at) {
			try { return new Date(at * 1000).toLocaleString(); } catch (e) { return String(at); }
		}
		function copyText(s, btn) {
			function done(ok) { if (btn) btn.textContent = ok ? '已复制' : '复制失败'; }
			if (window.navigator && window.navigator.clipboard && window.navigator.clipboard.writeText) {
				window.navigator.clipboard.writeText(s).then(function () { done(true); }, function () { done(false); });
				return;
			}
			try {
				var ta = document.createElement('textarea');
				ta.value = s;
				document.body.appendChild(ta);
				ta.select();
				done(document.execCommand('copy'));
				ta.parentNode.removeChild(ta);
			} catch (e) { done(false); }
		}

		function apply(ctx) {
			var root = document.createElement('div');
			root.id = 'xmuse-sidebar';
			var shadow = root.attachShadow({ mode: 'closed' });
			var style = document.createElement('style');
			style.textContent = CSS;

			var tab = el('div', 'tab', 'xmuse');
			var drawer = el('div', 'drawer');
			var header = el('header');
			var title = el('span', null, 'xmuse');
			var pushBtn = el('button', null, 'mode: overlay');
			var refreshBtn = el('button', null, '刷新');
			var closeBtn = el('button', null, '收起');
			header.appendChild(title);
			header.appendChild(pushBtn);
			header.appendChild(refreshBtn);
			header.appendChild(closeBtn);

			var main = el('main');
			// setup（未加入房间时）
			var setupSec = el('section');
			setupSec.appendChild(el('h3', null, '加入房间'));
			var setupErr = el('div', 'err');
			var roomDir = el('input'); roomDir.type = 'text'; roomDir.placeholder = '工作目录，如 C:\\Users\\me\\proj';
			var roomName = el('input'); roomName.type = 'text'; roomName.placeholder = '房间名';
			var roomBtn = el('button', 'primary', '开房间');
			var joinCode = el('input'); joinCode.type = 'text'; joinCode.placeholder = '邀请码，如 K7Q2-9F';
			var joinBtn = el('button', null, '加入');
			var r1 = el('div', 'row'); r1.appendChild(roomDir);
			var r2 = el('div', 'row'); r2.appendChild(roomName); r2.appendChild(roomBtn);
			var r3 = el('div', 'row'); r3.appendChild(joinCode); r3.appendChild(joinBtn);
			setupSec.appendChild(r1); setupSec.appendChild(r2); setupSec.appendChild(r3); setupSec.appendChild(setupErr);

			// 主视图各区
			var membersSec = el('section'); membersSec.appendChild(el('h3', null, '成员'));
			var membersBox = el('div'); membersSec.appendChild(membersBox);
			var threadsSec = el('section'); threadsSec.appendChild(el('h3', null, '话题 / 私聊'));
			var threadsBox = el('div', 'threads'); threadsSec.appendChild(threadsBox);
			var tlSec = el('section');
			var tlHead = el('h3', null, '时间线');
			var tlBox = el('div');
			var tlMoreBtn = el('button', null, '加载更早的');
			var tlAckBtn = el('button', null, '全部标已读');
			var tlRow = el('div', 'row'); tlRow.appendChild(tlMoreBtn); tlRow.appendChild(tlAckBtn);
			tlSec.appendChild(tlHead); tlSec.appendChild(tlRow); tlSec.appendChild(tlBox);
			var apprSec = el('section'); apprSec.appendChild(el('h3', null, '审批队列'));
			var apprBox = el('div'); apprSec.appendChild(apprBox);
			var alignSec = el('section'); alignSec.appendChild(el('h3', null, '对齐条目'));
			var alignBox = el('div'); alignSec.appendChild(alignBox);
			var invSec = el('section'); invSec.appendChild(el('h3', null, '邀请'));
			var invBox = el('div'); invSec.appendChild(invBox);
			var errLine = el('div', 'err');

			main.appendChild(setupSec);
			main.appendChild(membersSec);
			main.appendChild(threadsSec);
			main.appendChild(tlSec);
			main.appendChild(apprSec);
			main.appendChild(alignSec);
			main.appendChild(invSec);
			main.appendChild(errLine);

			var footer = el('footer');
			var toSel = el('select');
			var input = el('input'); input.type = 'text'; input.placeholder = '发消息，如 @coord 看一下';
			var sendBtn = el('button', 'primary', '发送');
			footer.appendChild(toSel); footer.appendChild(input); footer.appendChild(sendBtn);

			drawer.appendChild(header);
			drawer.appendChild(main);
			drawer.appendChild(footer);
			shadow.appendChild(style);
			shadow.appendChild(tab);
			shadow.appendChild(drawer);
			document.body.appendChild(root);

			var open = lsGet(KEY_OPEN) === '1';
			var push = lsGet(KEY_PUSH) === '1';
			var selThread = lsGet(KEY_THREAD) || 'all';
			var prevMargin = document.body.style.marginRight;
			var disposed = false;
			var state = null; // 最新 /v1/view 快照
			var version = 0;
			var polling = false;
			var extraOlder = []; // 经 /timeline 取到的更早消息（倒序插入头部）
			var setupMode = false;

			function layout() {
				if (open) drawer.setAttribute('data-open', ''); else drawer.removeAttribute('data-open');
				tab.style.right = open ? WIDTH + 'px' : '0';
				pushBtn.textContent = push ? 'mode: push' : 'mode: overlay';
				document.body.style.marginRight = open && push ? WIDTH + 'px' : prevMargin;
			}
			function setOpen(v) { open = v; lsSet(KEY_OPEN, v ? '1' : '0'); layout(); }
			tab.addEventListener('click', function () { setOpen(!open); });
			closeBtn.addEventListener('click', function () { setOpen(false); });
			pushBtn.addEventListener('click', function () { push = !push; lsSet(KEY_PUSH, push ? '1' : '0'); layout(); });
			refreshBtn.addEventListener('click', function () { version = 0; extraOlder = []; poll(true); });

			function api(path, opts) {
				return window.fetch(ROUTE + path, opts).then(function (r) {
					return r.text().then(function (t) {
						var data = null;
						try { data = t ? JSON.parse(t) : null; } catch (e) { data = { _raw: t }; }
						return { status: r.status, data: data };
					});
				});
			}
			function act(body, onOk) {
				errLine.textContent = '';
				api('/act', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
					.then(function (r) {
						if (r.status === 200) { if (onOk) onOk(r.data); poll(true); }
						else errLine.textContent = '操作失败 HTTP ' + r.status + '：' + JSON.stringify(r.data);
					})
					.catch(function (e) { errLine.textContent = '操作失败：' + e; });
			}

			function poll(force) {
				if (disposed || polling) return;
				if (!open && !force && state) return; // 收起时靠 tab 角标，不重画
				polling = true;
				api('/view?since=' + version + '&wait=25', { cache: 'no-store' }).then(function (r) {
					polling = false;
					if (disposed) return;
					if (r.status === 200 && r.data && typeof r.data.version === 'number') {
						state = r.data;
						version = r.data.version;
						setupMode = false;
						extraOlder = [];
						render();
						poll();
					} else if (r.status === 204) {
						poll();
					} else if (r.status === 409 || (r.data && (r.data.error === 'no_room' || r.data.error === 'room_exists'))) {
						setupMode = true;
						render();
						window.setTimeout(function () { poll(true); }, 5000);
					} else {
						errLine.textContent = '刷新失败 HTTP ' + r.status + '：' + JSON.stringify(r.data);
						window.setTimeout(function () { poll(true); }, 5000);
					}
				}).catch(function (e) {
					polling = false;
					if (disposed) return;
					errLine.textContent = '刷新失败：' + e + '（3 秒后重试）';
					window.setTimeout(function () { poll(true); }, 3000);
				});
			}

			function updateTab() {
				var n = 0;
				if (state) {
					for (var i = 0; i < (state.members || []).length; i++) n += state.members[i].unread || 0;
					n += (state.approvals || []).length;
				}
				tab.textContent = n > 0 ? 'xmuse(' + n + ')' : 'xmuse';
				if (n > 0) tab.setAttribute('data-alert', ''); else tab.removeAttribute('data-alert');
			}

			function render() {
				updateTab();
				setupSec.style.display = setupMode || !state ? '' : 'none';
				var showMain = !!state && !setupMode;
				membersSec.style.display = showMain ? '' : 'none';
				threadsSec.style.display = showMain ? '' : 'none';
				tlSec.style.display = showMain ? '' : 'none';
				apprSec.style.display = showMain ? '' : 'none';
				alignSec.style.display = showMain ? '' : 'none';
				invSec.style.display = showMain ? '' : 'none';
				footer.style.display = showMain ? '' : 'none';
				if (!showMain) return;
				title.textContent = 'xmuse · ' + (state.room ? state.room.name : '(无房间)') +
					' · 我是 ' + (state.me ? state.me.id : '?');
				renderMembers();
				renderThreads();
				renderTimeline();
				renderApprovals();
				renderAlign();
				renderInvite();
				renderToSel();
			}

			function renderMembers() {
				membersBox.textContent = '';
				var ms = state.members || [];
				if (!ms.length) membersBox.appendChild(el('div', 'dim', '（无成员）'));
				ms.forEach(function (m) {
					var row = el('div', 'member');
					row.appendChild(el('span', 'dot st-' + (m.status || 'offline')));
					var name = el('span', null, m.id + (m.online ? '' : '（离线）') + ' · ' + (m.role || ''));
					name.title = m.vendor + ' ' + (m.model || '');
					row.appendChild(name);
					if (m.description) {
						var d = el('span', 'desc grow', m.description);
						d.title = m.description;
						row.appendChild(d);
					} else row.appendChild(el('span', 'grow'));
					if (m.unread) row.appendChild(el('span', 'badge', String(m.unread)));
					if (m.paused) row.appendChild(el('span', 'badge gray', '暂停'));
					membersBox.appendChild(row);
				});
			}

			function renderThreads() {
				threadsBox.textContent = '';
				function btn(id, label, unread) {
					var b = el('button', id === selThread ? 'on' : null, label + (unread ? '(' + unread + ')' : ''));
					b.addEventListener('click', function () { selThread = id; lsSet(KEY_THREAD, id); render(); });
					threadsBox.appendChild(b);
				}
				btn('all', '全部', 0);
				(state.threads || []).forEach(function (t) { btn(t.id, t.title || t.id, t.unread || 0); });
			}

			function visibleMsgs() {
				var items = (extraOlder || []).concat(state.timeline || []);
				if (selThread === 'all') return items;
				return items.filter(function (m) { return m.thread === selThread; });
			}

			function renderTimeline() {
				tlBox.textContent = '';
				var items = visibleMsgs();
				var groups = {};
				var order = [];
				items.forEach(function (m) {
					if (!groups[m.thread]) { groups[m.thread] = []; order.push(m.thread); }
					groups[m.thread].push(m);
				});
				if (!order.length) tlBox.appendChild(el('div', 'dim', '（暂无消息）'));
				order.forEach(function (tid) {
					if (selThread === 'all') tlBox.appendChild(el('div', 'grp', tid));
					groups[tid].forEach(function (m) {
						var box = el('div', 'msg');
						if (m.for_me) box.setAttribute('data-me', '');
						var meta = el('div', 'meta', '#' + m.id + ' ' + m.thread + ' · ' + m.from +
							(m.via ? ' 经 ' + m.via : '') + ' · ' + fmtTime(m.at) +
							(m.kind && m.kind !== 'message' ? ' · ' + m.kind : '') + (m.for_me ? ' · @我' : ''));
						box.appendChild(meta);
						box.appendChild(el('div', null, m.text || ''));
						tlBox.appendChild(box);
					});
				});
				var hasMore = state.timeline_cursor && state.timeline_cursor.has_more;
				tlMoreBtn.disabled = !hasMore && !extraOlder.length ? false : false;
				tlMoreBtn.textContent = hasMore || extraOlder.length ? '加载更早的' : '没有更早了';
				tlMoreBtn.disabled = !(hasMore);
			}

			tlMoreBtn.addEventListener('click', function () {
				var oldest = state.timeline_cursor ? state.timeline_cursor.oldest : 0;
				if (extraOlder.length) oldest = extraOlder[0].id;
				api('/timeline?before=' + oldest + '&limit=50', { cache: 'no-store' }).then(function (r) {
					if (r.status === 200 && r.data) {
						extraOlder = (r.data.items || []).concat(extraOlder);
						if (state.timeline_cursor) state.timeline_cursor.has_more = !!r.data.has_more;
						renderTimeline();
					} else errLine.textContent = '加载更早失败 HTTP ' + r.status + '：' + JSON.stringify(r.data);
				}).catch(function (e) { errLine.textContent = '加载更早失败：' + e; });
			});
			tlAckBtn.addEventListener('click', function () {
				var ids = [];
				(state.timeline || []).forEach(function (m) { if (m.for_me) ids.push(m.id); });
				if (!ids.length) { errLine.textContent = '没有需要标已读的消息'; return; }
				act({ act: 'ack', ids: ids });
			});

			function renderToSel() {
				var cur = toSel.value;
				toSel.textContent = '';
				var opts = ['#room'];
				(state.threads || []).forEach(function (t) { if (opts.indexOf(t.id) < 0) opts.push(t.id); });
				(state.members || []).forEach(function (m) { if (state.me && m.id !== state.me.id) opts.push(m.id); });
				opts.forEach(function (o) {
					var op = document.createElement('option');
					op.value = o; op.textContent = o;
					toSel.appendChild(op);
				});
				if (selThread !== 'all' && opts.indexOf(selThread) >= 0) toSel.value = selThread;
				else if (opts.indexOf(cur) >= 0) toSel.value = cur;
			}

			function doSend() {
				var text = input.value;
				if (!text) return;
				sendBtn.disabled = true;
				act({ act: 'say', to: toSel.value || '#room', text: text }, function () { input.value = ''; });
				sendBtn.disabled = false;
			}
			sendBtn.addEventListener('click', doSend);
			input.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') doSend(); });

			function renderApprovals() {
				apprBox.textContent = '';
				var list = state.approvals || [];
				if (!list.length) apprBox.appendChild(el('div', 'dim', '（无待审批）'));
				list.forEach(function (a) {
					var box = el('div', 'appr');
					box.appendChild(el('div', null, a.id + ' · ' + a.kind + ' · ' + a.member + ' · ' + (a.summary || '')));
					if (a.detail) box.appendChild(el('div', 'dim', a.detail));
					var row = el('div', 'row');
					[['批准一次', 'once', 'primary'], ['总是', 'always', null], ['拒绝', 'reject', 'danger']].forEach(function (def) {
						var b = el('button', def[2], def[0]);
						b.addEventListener('click', function () { act({ act: 'approve', id: a.id, decision: def[1] }); });
						row.appendChild(b);
					});
					box.appendChild(row);
					apprBox.appendChild(box);
				});
			}

			function renderAlign() {
				alignBox.textContent = '';
				var list = state.alignment || [];
				if (!list.length) alignBox.appendChild(el('div', 'dim', '（无对齐条目）'));
				list.slice(-20).forEach(function (a) {
					var box = el('div', 'align');
					box.appendChild(el('div', null, a.id + ' [' + a.kind + '/' + (a.status || '?') + '] ' + (a.scope || '') +
						' · ' + (a.author || '')));
					box.appendChild(el('div', 'dim', a.text || ''));
					alignBox.appendChild(box);
				});
				if (list.length > 20) alignBox.appendChild(el('div', 'dim', '（仅显示最近 20 条，共 ' + list.length + ' 条）'));
			}

			var invBuilt = false;
			function renderInvite() {
				if (invBuilt) return;
				invBuilt = true;
				var vendor = el('select');
				['dsh', 'claude', 'opencode'].forEach(function (v) {
					var op = document.createElement('option'); op.value = v; op.textContent = v; vendor.appendChild(op);
				});
				var role = el('select');
				['executor', 'coordinator', 'reviewer'].forEach(function (v) {
					var op = document.createElement('option'); op.value = v; op.textContent = v; role.appendChild(op);
				});
				var desc = el('input'); desc.type = 'text'; desc.placeholder = '职责描述';
				var nm = el('input'); nm.type = 'text'; nm.placeholder = '名字（可选）';
				var go = el('button', 'primary', '生成邀请码');
				var out = el('div');
				var r1i = el('div', 'row'); r1i.appendChild(vendor); r1i.appendChild(role);
				var r2i = el('div', 'row'); r2i.appendChild(desc);
				var r3i = el('div', 'row'); r3i.appendChild(nm); r3i.appendChild(go);
				invBox.appendChild(r1i); invBox.appendChild(r2i); invBox.appendChild(r3i); invBox.appendChild(out);
				go.addEventListener('click', function () {
					out.textContent = '';
					var body = { act: 'invite', vendor: vendor.value, role: role.value, description: desc.value };
					if (nm.value) body.name = nm.value;
					api('/act', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
						.then(function (r) {
							if (r.status !== 200 || !r.data || !r.data.code) {
								out.appendChild(el('div', 'err', '邀请失败 HTTP ' + r.status + '：' + JSON.stringify(r.data)));
								return;
							}
							out.appendChild(el('div', null, '邀请码：'));
							out.appendChild(el('span', 'code', r.data.code));
							var cmd = el('div'); cmd.appendChild(el('span', 'code', r.data.command || ('/xmuse join ' + r.data.code)));
							out.appendChild(cmd);
							var cp = el('button', null, '复制命令');
							cp.addEventListener('click', function () { copyText(r.data.command || ('/xmuse join ' + r.data.code), cp); });
							out.appendChild(cp);
						})
						.catch(function (e) { out.appendChild(el('div', 'err', '邀请失败：' + e)); });
				});
			}

			roomBtn.addEventListener('click', function () {
				setupErr.textContent = '';
				if (!roomDir.value || !roomName.value) { setupErr.textContent = '请填写工作目录和房间名'; return; }
				window.fetch(ROUTE + '/rooms', {
					method: 'POST', headers: { 'content-type': 'application/json' },
					body: JSON.stringify({ dir: roomDir.value, name: roomName.value }),
				}).then(function (r) {
					return r.text().then(function (t) { return { status: r.status, data: JSON.parse(t || '{}') }; });
				}).then(function (r) {
					if (r.status === 200) { setupMode = false; version = 0; poll(true); }
					else setupErr.textContent = '开房间失败 HTTP ' + r.status + '：' + JSON.stringify(r.data);
				}).catch(function (e) { setupErr.textContent = '开房间失败：' + e; });
			});
			joinBtn.addEventListener('click', function () {
				setupErr.textContent = '';
				if (!joinCode.value) { setupErr.textContent = '请填写邀请码'; return; }
				window.fetch(ROUTE + '/join', {
					method: 'POST', headers: { 'content-type': 'application/json' },
					body: JSON.stringify({ code: joinCode.value.trim() }),
				}).then(function (r) {
					return r.text().then(function (t) { return { status: r.status, data: JSON.parse(t || '{}') }; });
				}).then(function (r) {
					if (r.status === 200) { setupMode = false; version = 0; poll(true); }
					else setupErr.textContent = '加入失败 HTTP ' + r.status + '：' + JSON.stringify(r.data);
				}).catch(function (e) { setupErr.textContent = '加入失败：' + e; });
			});

			layout();
			poll(true);

			ctx.effect(function dispose() {
				return function () {
					disposed = true;
					document.body.style.marginRight = prevMargin;
					if (root.parentNode !== null) root.parentNode.removeChild(root);
				};
			}, 'xmuse-sidebar: drawer');
		}

		exports.apply = apply;
		exports.inject = [];
		exports.name = 'xmuse-sidebar';
		return module.exports;
	},
});
