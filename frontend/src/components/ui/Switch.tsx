/** 扁平风格开关（圆角为 0，与全站设计一致的方形滑块） */
export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center transition-colors ${checked ? 'bg-brand' : 'bg-surface-border'}`}
    >
      <span
        className={`inline-block h-5 w-5 transform bg-white shadow-sm transition-transform ${checked ? 'translate-x-[22px]' : 'translate-x-0.5'}`}
      />
    </button>
  )
}
