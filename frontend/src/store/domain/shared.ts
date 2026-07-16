export type DomainSelector<TState, TValue> = (state: TState) => TValue;

/**
 * A domain slice owns these keys in the root store.  The root remains responsible
 * for composing slices so cross-domain transitions can stay atomic.
 */
export type DomainCapability<TState, TKey extends keyof TState> = Pick<TState, TKey>;

export function selectField<TState, TKey extends keyof TState>(
  key: TKey
): DomainSelector<TState, TState[TKey]> {
  return (state) => state[key];
}
