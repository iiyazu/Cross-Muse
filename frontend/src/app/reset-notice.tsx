/**
 * Placeholder served while the presentation layer is rebuilt. It carries no styling, no
 * components and no store wiring on purpose: see frontend/README.md for what stays and what
 * the rebuild must honour.
 */
export function ResetNotice() {
  return (
    <main data-testid="presentation-reset">
      <h1>xmuse Workroom</h1>
      <p>前端展示层正在重建。对接层（src/lib、src/store、src/app/api）保持不变。</p>
    </main>
  );
}
