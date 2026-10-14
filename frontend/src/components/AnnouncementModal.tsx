import { ExternalLink, MessageCircle, X } from 'lucide-react'
import type { AnnouncementContent } from '@/types'

interface Props {
  announcement: AnnouncementContent
  onClose: () => void
  /** 预览模式：z-index 更高（盖在管理页之上），其它与正式弹窗一致 */
  preview?: boolean
}

/** 公告弹窗的纯展示层：正式弹窗与管理员预览共用，内容全部来自 announcement */
export function AnnouncementModal({ announcement, onClose, preview = false }: Props) {
  const { badge, title, content, image_url, button_text, link_text, link_url } = announcement

  return (
    <div
      className={`fixed inset-0 ${preview ? 'z-[120]' : 'z-[80]'} flex items-center justify-center bg-content/40 px-4 py-6`}
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-[420px] max-h-[90vh] overflow-y-auto border border-white/75 bg-[linear-gradient(180deg,rgba(255,255,255,0.98)_0%,rgba(255,247,240,0.99)_100%)] shadow-xl animate-scale-in"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title || '公告'}
      >
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand via-gold to-brand" />
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 z-10 p-2 text-content-tertiary hover:bg-surface-hover hover:text-content"
          aria-label="关闭公告"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="px-6 pb-6 pt-7">
          {badge && (
            <div className="mb-4 inline-flex items-center gap-2 bg-brand/10 px-3 py-1.5 text-xs font-medium text-brand">
              <MessageCircle className="h-3.5 w-3.5" />
              {badge}
            </div>
          )}
          {title && <h2 className="text-xl font-bold text-content">{title}</h2>}
          {content && (
            <p className="mt-2 whitespace-pre-line break-words text-sm leading-6 text-content-secondary">{content}</p>
          )}

          {image_url && (
            <div className="mt-5 border border-surface-border bg-white p-3 shadow-card">
              <img src={image_url} alt={title || '公告图片'} className="mx-auto max-h-[320px] w-full max-w-[320px] object-contain" />
            </div>
          )}

          {link_url && (
            <a
              href={link_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-brand hover:underline"
            >
              {link_text || link_url}
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}

          <button type="button" onClick={onClose} className="fanqie-primary-btn mt-5 w-full">
            {button_text || '我知道了'}
          </button>
        </div>
      </div>
    </div>
  )
}
