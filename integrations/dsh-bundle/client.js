/**
 * xmuse dsh-bundle 侧栏（抽屉）前端：单文件、无 import、无资产，DOM-only。
 * 由宿主经 GET /xmuse/sidebar.js 下发，以 window.__ModuleLoader__.load 注入，
 * 在 dsh 页面右缘画一个可收起的抽屉。令牌只在宿主进程里，这里只有同源 fetch。
 *
 * 内容（XMUSE2-VIEW-API v0 + v0.1 §8 的 /v1/view 快照直渲染）：
 *   本机房间一键加入、成员列表（状态/在线/职责/未读）与成员菜单（设主控/改角色/暂停/移出/私聊/拉群）、
 *   添加成员、新建私有群（锁标记、群成员移出）、时间线（按话题·私聊分组、@我高亮、可加载更早）、
 *   发消息、审批队列（批准一次/总是/拒绝，含 share）、对齐条目摘要、开房间/邀请表单（含邀请码与可复制命令）。
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
			'.menu{border:1px solid #ccd;border-radius:6px;padding:4px 6px;margin:4px 0;background:#fafaff}',
			'.tag{display:inline-block;border:1px solid #2b5fd9;color:#2b5fd9;border-radius:9px;padding:0 6px;font-size:11px;margin:2px 4px 2px 0}',
			'.tag.warn{border-color:#b3261e;color:#b3261e}',
			'.chk{display:flex;gap:6px;align-items:center;margin:2px 0}',
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
			// 本机房间（一键加入；邀请码是次要入口，留在 setup 里）
			var roomsSec = el('section');
			roomsSec.appendChild(el('h3', null, '本机房间（一键加入）'));
			var roomsBox = el('div');
			var roomsErr = el('div', 'err');
			var roomsRow = el('div', 'row');
			var roomsRefresh = el('button', null, '刷新列表');
			roomsRow.appendChild(roomsRefresh);
			roomsSec.appendChild(roomsBox);
			roomsSec.appendChild(roomsRow);
			roomsSec.appendChild(roomsErr);
			// setup（未加入房间时：开房间 / 邀请码加入）
			var setupSec = el('section');
			setupSec.appendChild(el('h3', null, '开房间或邀请码加入'));
			var setupErr = el('div', 'err');
			var roomDir = el('input'); roomDir.type = 'text'; roomDir.placeholder = '工作目录，如 C:\\Users\\me\\proj';
			var roomName = el('input'); roomName.type = 'text'; roomName.placeholder = '房间名';
			var roomBtn = el('button', 'primary', '开房间');
			var joinCode = el('input'); joinCode.type = 'text'; joinCode.placeholder = '邀请码，如 AB12-CD';
			var joinBtn = el('button', null, '加入');
			var r1 = el('div', 'row'); r1.appendChild(roomDir);
			var r2 = el('div', 'row'); r2.appendChild(roomName); r2.appendChild(roomBtn);
			var r3 = el('div', 'row'); r3.appendChild(joinCode); r3.appendChild(joinBtn);
			setupSec.appendChild(r1); setupSec.appendChild(r2); setupSec.appendChild(r3); setupSec.appendChild(setupErr);

			// 主视图各区
			var membersSec = el('section'); membersSec.appendChild(el('h3', null, '成员'));
			var membersBox = el('div'); membersSec.appendChild(membersBox);
			var hostSec = el('section'); hostSec.appendChild(el('h3', null, '主控在等谁'));
			var hostBox = el('div'); hostSec.appendChild(hostBox);
			var hostRow = el('div', 'row');
			var wakeBtn = el('button', 'primary', '现在叫醒主控');
			hostRow.appendChild(wakeBtn); hostSec.appendChild(hostRow);
			var hostOut = el('div'); hostSec.appendChild(hostOut);
			wakeBtn.addEventListener('click', function () {
				hostOut.textContent = '';
				act({ act: 'wake_host' }, function (data) {
					hostOut.textContent = '已叫醒，放出 ' + (data && data.released !== undefined ? data.released : '?') + ' 条结果';
				});
			});
			var threadsSec = el('section'); threadsSec.appendChild(el('h3', null, '话题 / 私聊'));
			var threadsBox = el('div', 'threads'); threadsSec.appendChild(threadsBox);
			var grpMembersBox = el('div'); threadsSec.appendChild(grpMembersBox);
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
			var addSec = el('section'); addSec.appendChild(el('h3', null, '添加成员（hub 起回合）'));
			var addBox = el('div'); addSec.appendChild(addBox);
			var grpSec = el('section'); grpSec.appendChild(el('h3', null, '新建私有群'));
			var grpBox = el('div'); grpSec.appendChild(grpBox);
			var errLine = el('div', 'err');

			main.appendChild(roomsSec);
			main.appendChild(setupSec);
			main.appendChild(membersSec);
			main.appendChild(hostSec);
			main.appendChild(threadsSec);
			main.appendChild(tlSec);
			main.appendChild(apprSec);
			main.appendChild(alignSec);
			main.appendChild(invSec);
			main.appendChild(addSec);
			main.appendChild(grpSec);
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
			var openMenu = null; // 展开菜单的成员 id（同时只展开一个）
			var menuDraft = { role: '', description: '', model: '' }; // 菜单里编辑框的草稿（重画不丢）
			var roomsCache = null; // GET /xmuse/rooms 的结果
			var grpChecked = {}; // 新建群勾选的成员 id

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
				if (setupMode || !state) loadRooms(false);
				membersSec.style.display = showMain ? '' : 'none';
				hostSec.style.display = showMain ? '' : 'none';
				threadsSec.style.display = showMain ? '' : 'none';
				tlSec.style.display = showMain ? '' : 'none';
				apprSec.style.display = showMain ? '' : 'none';
				alignSec.style.display = showMain ? '' : 'none';
				invSec.style.display = showMain ? '' : 'none';
				addSec.style.display = showMain ? '' : 'none';
				grpSec.style.display = showMain ? '' : 'none';
				footer.style.display = showMain ? '' : 'none';
				if (!showMain) return;
				title.textContent = 'xmuse · ' + (state.room ? state.room.name : '(无房间)') +
					' · 我是 ' + (state.me ? state.me.id : '?');
				renderMembers();
				renderHostWait();
				renderThreads();
				renderTimeline();
				renderApprovals();
				renderAlign();
				renderInvite();
				renderAddMember();
				renderNewGroup();
				renderToSel();
			}

			function dmId(a, b) { return 'dm:' + [a, b].sort().join('+'); }

			// 本机房间列表：每间一个加入按钮（约定 8.1，一次点击）。key 只在宿主侧，浏览器只传 room_id。
			function loadRooms(force) {
				if (roomsCache && !force) { renderRooms(); return; }
				window.fetch(ROUTE + '/rooms', { cache: 'no-store' }).then(function (r) {
					return r.text().then(function (t) {
						var data = null;
						try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
						if (r.status === 200 && data) roomsCache = data; else roomsCache = { hubs: [], note: 'HTTP ' + r.status };
						renderRooms();
					});
				}).catch(function (e) { roomsCache = { hubs: [], note: String(e) }; renderRooms(); });
			}
			roomsRefresh.addEventListener('click', function () { roomsCache = null; roomsErr.textContent = ''; loadRooms(true); });
			function renderRooms() {
				roomsBox.textContent = '';
				roomsErr.textContent = '';
				var hubs = (roomsCache && roomsCache.hubs) || [];
				if (roomsCache && roomsCache.note) roomsBox.appendChild(el('div', 'dim', roomsCache.note));
				if (!hubs.length) roomsBox.appendChild(el('div', 'dim', roomsCache ? '（本机无房间）' : '加载中…'));
				var curRoom = state && state.room ? state.room.id : null;
				hubs.forEach(function (h) {
					var row = el('div', 'row');
					var label = el('span', 'grow', (h.room_id === curRoom ? '● ' : '') +
						(h.name || h.room_id) + ' · ' + (h.dir || '') + ' · 主控 ' + (h.host || '?'));
					row.appendChild(label);
					if (h.room_id === curRoom) {
						row.appendChild(el('span', 'dim', '当前'));
					} else {
						var jb = el('button', 'primary', '加入');
						(function (rid) {
							jb.addEventListener('click', function () {
								roomsErr.textContent = '';
								jb.disabled = true;
								window.fetch(ROUTE + '/join-local', {
									method: 'POST', headers: { 'content-type': 'application/json' },
									body: JSON.stringify({ room_id: rid }),
								}).then(function (r) {
									return r.text().then(function (t) { return { status: r.status, data: JSON.parse(t || '{}') }; });
								}).then(function (r) {
									jb.disabled = false;
									if (r.status === 200) { setupMode = false; version = 0; extraOlder = []; roomsCache = null; poll(true); }
									else roomsErr.textContent = '加入失败 HTTP ' + r.status + '：' + JSON.stringify(r.data);
								}).catch(function (e) { jb.disabled = false; roomsErr.textContent = '加入失败：' + e; });
							});
						})(h.room_id);
						row.appendChild(jb);
					}
					roomsBox.appendChild(row);
				});
			}

			function renderMembers() {
				membersBox.textContent = '';
				var ms = state.members || [];
				if (!ms.length) membersBox.appendChild(el('div', 'dim', '（无成员）'));
				var privates = (state.threads || []).filter(function (t) { return t.private; });
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
					if (m.wakes_hour !== undefined && m.wakes_hour !== null) {
						var wh = el('span', 'badge gray', '唤醒' + m.wakes_hour + '/h');
						wh.title = '近 1 小时唤醒次数';
						row.appendChild(wh);
					}
					var more = el('button', null, openMenu === m.id ? '收起' : '⋯');
					more.title = '成员菜单';
					(function (mid) {
						more.addEventListener('click', function () {
							openMenu = (openMenu === mid ? null : mid);
							menuDraft = { role: '', description: '', model: '' };
							renderMembers();
						});
					})(m.id);
					row.appendChild(more);
					membersBox.appendChild(row);
					if (openMenu === m.id) membersBox.appendChild(memberMenu(m, privates));
				});
			}

			// 成员菜单（抽屉里做，不用系统右键）：主控/改角色/暂停/移出/私聊/拉群。
			function memberMenu(m, privates) {
				var menu = el('div', 'menu');
				function item(label, fn, cls) {
					var b = el('button', cls || null, label);
					b.addEventListener('click', function () { openMenu = null; fn(); });
					menu.appendChild(b);
					return b;
				}
				item('设为主控', function () { act({ act: 'transfer_host', member: m.id }); });
				item(m.paused ? '恢复' : '暂停', function () { act({ act: m.paused ? 'resume' : 'pause', member: m.id }); });
				item('移出', function () { act({ act: 'remove', member: m.id }); }, 'danger');
				item('私聊', function () {
					if (!state.me) return;
					selThread = dmId(state.me.id, m.id);
					lsSet(KEY_THREAD, selThread);
					render();
				});
				// 改角色和描述（只发填了的项）
				var er = el('div', 'row');
				var roleSel = el('select');
				['', 'executor', 'coordinator', 'reviewer'].forEach(function (v, i) {
					var op = document.createElement('option');
					op.value = v; op.textContent = i === 0 ? '角色（不改）' : v;
					roleSel.appendChild(op);
				});
				roleSel.value = menuDraft.role;
				roleSel.addEventListener('change', function () { menuDraft.role = roleSel.value; });
				var descIn = el('input'); descIn.type = 'text'; descIn.placeholder = '职责描述';
				descIn.value = menuDraft.description;
				descIn.addEventListener('input', function () { menuDraft.description = descIn.value; });
				var modelIn = el('input'); modelIn.type = 'text'; modelIn.placeholder = '模型（可选）';
				modelIn.value = menuDraft.model;
				modelIn.addEventListener('input', function () { menuDraft.model = modelIn.value; });
				var save = el('button', 'primary', '保存修改');
				save.addEventListener('click', function () {
					var body = { act: 'member_edit', member: m.id };
					if (menuDraft.role) body.role = menuDraft.role;
					if (menuDraft.description) body.description = menuDraft.description;
					if (menuDraft.model) body.model = menuDraft.model;
					if (!menuDraft.role && !menuDraft.description && !menuDraft.model) {
						errLine.textContent = '至少改一项（角色/描述/模型）';
						return;
					}
					openMenu = null;
					menuDraft = { role: '', description: '', model: '' };
					act(body);
				});
				er.appendChild(roleSel); er.appendChild(descIn);
				var er2 = el('div', 'row'); er2.appendChild(modelIn); er2.appendChild(save);
				menu.appendChild(er); menu.appendChild(er2);
				// 拉进群（选一个私有群）
				if (!privates.length) {
					menu.appendChild(el('div', 'dim', '暂无私有群，先在下面新建群'));
				} else {
					var gr = el('div', 'row');
					var gsel = el('select');
					privates.forEach(function (t) {
						var op = document.createElement('option');
						op.value = t.id; op.textContent = t.title || t.id;
						gsel.appendChild(op);
					});
					var add = el('button', null, '拉进群');
					add.addEventListener('click', function () {
						openMenu = null;
						act({ act: 'thread_add', thread: gsel.value, member: m.id });
					});
					gr.appendChild(gsel); gr.appendChild(add);
					menu.appendChild(gr);
				}
				return menu;
			}

			// 主控在等谁（view.host_wait）：等哪几个成员、压住几条结果、多久后自动唤醒 + 现在叫醒。
			function renderHostWait() {
				hostBox.textContent = '';
				var hw = state.host_wait || { waiting_on: [], results_held: 0, wake_at: null };
				var w = hw.waiting_on || [];
				if (!w.length && !(hw.results_held > 0)) {
					hostBox.appendChild(el('div', 'dim', '（主控暂无等待）'));
					return;
				}
				w.forEach(function (x) {
					hostBox.appendChild(el('div', null, '等 ' + x.member +
						'（任务 ' + x.handoff_id + '，自 ' + fmtTime(x.since) + '）'));
				});
				if (hw.results_held > 0) hostBox.appendChild(el('div', null, '压住了 ' + hw.results_held + ' 条结果'));
				if (hw.wake_at) {
					var left = Math.max(0, Math.round(hw.wake_at - Date.now() / 1000));
					hostBox.appendChild(el('div', 'dim', '约 ' + left + ' 秒后自动唤醒'));
				}
			}

			function renderThreads() {
				threadsBox.textContent = '';
				grpMembersBox.textContent = '';
				function btn(id, label, unread, priv) {
					var b = el('button', id === selThread ? 'on' : null,
						(priv ? '🔒' : '') + label + (unread ? '(' + unread + ')' : ''));
					b.addEventListener('click', function () { selThread = id; lsSet(KEY_THREAD, id); render(); });
					threadsBox.appendChild(b);
				}
				btn('all', '全部', 0, false);
				(state.threads || []).forEach(function (t) { btn(t.id, t.title || t.id, t.unread || 0, !!t.private); });
				// 选中的私有群：列成员，可移出（thread_remove）。
				var sel = null;
				(state.threads || []).forEach(function (t) { if (t.id === selThread && t.private) sel = t; });
				if (sel) {
					grpMembersBox.appendChild(el('div', 'grp', '群成员（' + sel.id + '）'));
					(sel.members || []).forEach(function (mid) {
						var row = el('div', 'row');
						row.appendChild(el('span', 'grow', mid));
						if (mid !== 'human') {
							var rm = el('button', null, '移出');
							(function (tid, id) {
								rm.addEventListener('click', function () { act({ act: 'thread_remove', thread: tid, member: id }); });
							})(sel.id, mid);
							row.appendChild(rm);
						}
						grpMembersBox.appendChild(row);
					});
				}
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
						// done 结果标签（8.4）：outcome + hub 改判 + 证据 + 分享来源。
						if (m.kind === 'done' && m.outcome) {
							var tag = el('span', 'tag', '结果：' + m.outcome);
							box.appendChild(tag);
							if (m.outcome_by === 'hub') {
								var re = el('span', 'tag warn', 'hub 改判' + (m.outcome_reason ? '：' + m.outcome_reason : ''));
								re.title = m.outcome_reason || 'hub 改判';
								box.appendChild(re);
							}
						}
						if (m.evidence_status === 'unverified') {
							var ev = el('span', 'tag warn', '未核实' +
								((m.evidence_problems && m.evidence_problems.length) ? '：' + m.evidence_problems.join('；') : ''));
							ev.title = (m.evidence_problems || []).join('; ');
							box.appendChild(ev);
						}
						if (m.shared_from && m.shared_from.member) {
							box.appendChild(el('div', 'meta', '分享自 ' + m.shared_from.member +
								'（#' + m.shared_from.message_id + '）'));
						}
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
					// 除 shell 外还有 kind=alignment（id 如 E12）和 kind=resume（id 如 resume:<成员>），
					// 都用 approve 处理；对齐提案可能没有 member/summary，用 author/text 兜底。
					var who = a.member || a.author || '';
					box.appendChild(el('div', null, a.id + ' · ' + a.kind + (who ? ' · ' + who : '') +
						' · ' + (a.summary || a.text || '') + (a.risk === 'high' ? ' · 高风险' : '')));
					// share 审批的 detail 是对象：显示摘录、目标和原因（成员令牌看不到这类审批）。
					if (a.detail && typeof a.detail === 'object') {
						if (a.detail.excerpt) box.appendChild(el('div', null, a.detail.excerpt));
						var bits = [];
						if (a.detail.message_id !== undefined) bits.push('#' + a.detail.message_id);
						if (a.detail.to) bits.push('给 ' + a.detail.to);
						if (a.detail.why) bits.push('原因 ' + a.detail.why);
						if (bits.length) box.appendChild(el('div', 'dim', bits.join(' · ')));
					} else if (a.detail) box.appendChild(el('div', 'dim', a.detail));
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

			var addBuilt = false;
			function renderAddMember() {
				if (addBuilt) return;
				addBuilt = true;
				// 添加成员（member_add：登记一个由 hub 起回合的成员）。输入框只建一次，重画不丢字。
				var vendor = el('select');
				['dsh', 'claude', 'opencode'].forEach(function (v) {
					var op = document.createElement('option'); op.value = v; op.textContent = v; vendor.appendChild(op);
				});
				var model = el('input'); model.type = 'text'; model.placeholder = '模型（可选）';
				var role = el('select');
				['executor', 'coordinator', 'reviewer'].forEach(function (v) {
					var op = document.createElement('option'); op.value = v; op.textContent = v; role.appendChild(op);
				});
				var desc = el('input'); desc.type = 'text'; desc.placeholder = '职责描述';
				var nm = el('input'); nm.type = 'text'; nm.placeholder = '名字（可选）';
				var go = el('button', 'primary', '添加成员');
				var out = el('div');
				var a1 = el('div', 'row'); a1.appendChild(vendor); a1.appendChild(model);
				var a2 = el('div', 'row'); a2.appendChild(role); a2.appendChild(desc);
				var a3 = el('div', 'row'); a3.appendChild(nm); a3.appendChild(go);
				addBox.appendChild(a1); addBox.appendChild(a2); addBox.appendChild(a3); addBox.appendChild(out);
				go.addEventListener('click', function () {
					out.textContent = '';
					var body = { act: 'member_add', vendor: vendor.value, role: role.value };
					if (model.value) body.model = model.value;
					if (desc.value) body.description = desc.value;
					if (nm.value) body.name = nm.value;
					api('/act', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
						.then(function (r) {
							if (r.status !== 200 || !r.data || !r.data.member_id) {
								out.appendChild(el('div', 'err', '添加失败 HTTP ' + r.status + '：' + JSON.stringify(r.data)));
								return;
							}
							out.appendChild(el('div', null, '已添加成员：' + r.data.member_id));
							poll(true);
						})
						.catch(function (e) { out.appendChild(el('div', 'err', '添加失败：' + e)); });
				});
			}

			var grpBuilt = false;
			var grpBoxes = null;
			function renderNewGroup() {
				// 新建私有群（thread_new）：id 形如 #名字，用户自动在内。勾选框每次重画，勾选状态保留。
				if (!grpBuilt) {
					grpBuilt = true;
					var gid = el('input'); gid.type = 'text'; gid.placeholder = '群 id，如 #g1';
					var gtitle = el('input'); gtitle.type = 'text'; gtitle.placeholder = '标题（可选）';
					grpBoxes = el('div');
					var go = el('button', 'primary', '新建群');
					var out = el('div');
					var g1 = el('div', 'row'); g1.appendChild(gid); g1.appendChild(gtitle);
					var g3 = el('div', 'row'); g3.appendChild(go);
					grpBox.appendChild(g1); grpBox.appendChild(grpBoxes); grpBox.appendChild(g3); grpBox.appendChild(out);
					go.addEventListener('click', function () {
						out.textContent = '';
						if (!gid.value || gid.value.charAt(0) !== '#') { out.appendChild(el('div', 'err', '群 id 形如 #名字')); return; }
						var members = [];
						for (var id in grpChecked) if (grpChecked[id]) members.push(id);
						api('/act', {
							method: 'POST', headers: { 'content-type': 'application/json' },
							body: JSON.stringify({ act: 'thread_new', id: gid.value.trim(), members: members, title: gtitle.value }),
						}).then(function (r) {
							if (r.status !== 200 || !r.data || !r.data.thread) {
								out.appendChild(el('div', 'err', '新建失败 HTTP ' + r.status + '：' + JSON.stringify(r.data)));
								return;
							}
							out.appendChild(el('div', null, '已建群：' + r.data.thread));
							grpChecked = {};
							poll(true);
						}).catch(function (e) { out.appendChild(el('div', 'err', '新建失败：' + e)); });
					});
				}
				grpBoxes.textContent = '';
				(state.members || []).forEach(function (m) {
					if (state.me && m.id === state.me.id) return;
					var lab = el('label', 'chk');
					var cb = document.createElement('input');
					cb.type = 'checkbox';
					cb.checked = !!grpChecked[m.id];
					(function (id) {
						cb.addEventListener('change', function () { grpChecked[id] = cb.checked; });
					})(m.id);
					lab.appendChild(cb);
					lab.appendChild(el('span', null, m.id + ' · ' + (m.role || '')));
					grpBoxes.appendChild(lab);
				});
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
