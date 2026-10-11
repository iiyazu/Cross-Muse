/**
 * Browser half of dsh-drawer-probe (D0 feasibility probe, not product code).
 *
 * A collapsible drawer in a closed shadow root, fixed to the right edge of the dsh page:
 *   - a small tab "xmuse" at the edge toggles it (state kept in localStorage);
 *   - the body polls GET /xmuse-probe/view every 2 s (host route -> loopback hub) and shows the reply;
 *   - an Input + Send button POSTs {text} to /xmuse-probe/act;
 *   - a "push" switch reserves room by adding margin-right to <body> instead of overlapping the page.
 * Everything is DOM-only: no framework, same pattern as dsh-pixel-maid (window.__ModuleLoader__.load).
 */
window.__ModuleLoader__.load({
	id: 'dsh-drawer-probe',
	factory: () => {
		var module = { exports: {} };
		var exports = module.exports;

		var ROUTE = '/xmuse-probe';
		var WIDTH = 340;
		var KEY_OPEN = 'xmuse-drawer-probe:open';
		var KEY_PUSH = 'xmuse-drawer-probe:push';

		var CSS = [
			':host{all:initial}',
			'*{box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13px}',
			'.tab{position:fixed;top:40%;right:0;z-index:2147483000;writing-mode:vertical-rl;padding:10px 6px;',
			'background:#2b5fd9;color:#fff;border-radius:8px 0 0 8px;cursor:pointer;user-select:none;pointer-events:auto}',
			'.drawer{position:fixed;top:0;right:0;bottom:0;width:' + WIDTH + 'px;z-index:2147482999;',
			'background:#fff;color:#1b1b1b;border-left:1px solid #ccd;box-shadow:-4px 0 14px rgba(0,0,0,.18);',
			'display:none;flex-direction:column;pointer-events:auto}',
			'.drawer[data-open]{display:flex}',
			'header{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #e3e3ee;font-weight:600}',
			'header span{flex:1}',
			'button{border:1px solid #99a;background:#f4f5fb;border-radius:6px;padding:3px 9px;cursor:pointer}',
			'main{flex:1;overflow:auto;padding:10px 12px;white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,Consolas,monospace;font-size:12px}',
			'footer{display:flex;gap:6px;padding:10px 12px;border-top:1px solid #e3e3ee}',
			'input[type=text]{flex:1;border:1px solid #99a;border-radius:6px;padding:4px 8px}',
			'.dim{color:#777}',
		].join('\n');

		function lsGet(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
		function lsSet(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* ignore */ } }

		function apply(ctx) {
			var root = document.createElement('div');
			root.id = 'dsh-drawer-probe';
			var shadow = root.attachShadow({ mode: 'closed' });
			var style = document.createElement('style');
			style.textContent = CSS;

			var tab = document.createElement('div');
			tab.className = 'tab';
			tab.textContent = 'xmuse';

			var drawer = document.createElement('div');
			drawer.className = 'drawer';
			var header = document.createElement('header');
			var title = document.createElement('span');
			title.textContent = 'xmuse room (probe)';
			var pushBtn = document.createElement('button');
			var closeBtn = document.createElement('button');
			closeBtn.textContent = 'collapse';
			header.appendChild(title);
			header.appendChild(pushBtn);
			header.appendChild(closeBtn);
			var main = document.createElement('main');
			main.textContent = 'loading...';
			var footer = document.createElement('footer');
			var input = document.createElement('input');
			input.type = 'text';
			input.placeholder = '@claude hello';
			var send = document.createElement('button');
			send.textContent = 'Send';
			footer.appendChild(input);
			footer.appendChild(send);
			drawer.appendChild(header);
			drawer.appendChild(main);
			drawer.appendChild(footer);
			shadow.appendChild(style);
			shadow.appendChild(tab);
			shadow.appendChild(drawer);
			document.body.appendChild(root);

			var open = lsGet(KEY_OPEN) === '1';
			var push = lsGet(KEY_PUSH) === '1';
			var prevMargin = document.body.style.marginRight;
			var disposed = false;

			function layout() {
				if (open) drawer.setAttribute('data-open', ''); else drawer.removeAttribute('data-open');
				tab.style.right = open ? WIDTH + 'px' : '0';
				pushBtn.textContent = push ? 'mode: push' : 'mode: overlay';
				document.body.style.marginRight = open && push ? WIDTH + 'px' : prevMargin;
			}
			function setOpen(v) { open = v; lsSet(KEY_OPEN, v ? '1' : '0'); layout(); if (v) poll(); }
			tab.addEventListener('click', function () { setOpen(!open); });
			closeBtn.addEventListener('click', function () { setOpen(false); });
			pushBtn.addEventListener('click', function () { push = !push; lsSet(KEY_PUSH, push ? '1' : '0'); layout(); });

			function show(obj) {
				main.textContent = new Date().toLocaleTimeString() + '\n' + (typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2)) +
					'\n\nviewport ' + window.innerWidth + 'x' + window.innerHeight + ' dpr ' + window.devicePixelRatio;
			}
			function poll() {
				if (disposed || !open) return;
				fetch(ROUTE + '/view', { cache: 'no-store' })
					.then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
					.then(function (r) { show('HTTP ' + r.status + '\n' + r.text); })
					.catch(function (e) { show('fetch failed: ' + e); });
			}
			function doSend() {
				var text = input.value;
				if (!text) return;
				fetch(ROUTE + '/act', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ act: 'say', text: text }) })
					.then(function (r) { return r.text(); })
					.then(function (t) { input.value = ''; show('sent -> ' + t); })
					.catch(function (e) { show('send failed: ' + e); });
			}
			send.addEventListener('click', doSend);
			input.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') doSend(); });

			var timer = setInterval(poll, 2000);
			layout();
			poll();

			ctx.effect(function dispose() {
				return function () {
					disposed = true;
					clearInterval(timer);
					document.body.style.marginRight = prevMargin;
					if (root.parentNode !== null) root.parentNode.removeChild(root);
				};
			}, 'dsh-drawer-probe: drawer');
		}

		exports.apply = apply;
		exports.inject = [];
		exports.name = 'dsh-drawer-probe';
		return module.exports;
	},
});
