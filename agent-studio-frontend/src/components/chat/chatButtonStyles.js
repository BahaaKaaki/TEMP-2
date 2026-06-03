/**
 * Chat toolbar / composer buttons — matches builder NAVBAR.secondaryButton
 * (dark rose-tinted base, white label, subtle rose border — not solid red).
 */
export const CHAT_SECONDARY_BTN =
  'font-bold text-white bg-[#2a1d21] border border-[rgba(217,56,84,0.42)] shadow-[inset_0_1px_0_rgba(217,56,84,0.18)] hover:bg-[#3b1c21] hover:border-[rgba(217,56,84,0.72)] hover:shadow-[inset_0_1px_0_rgba(217,56,84,0.28),0_0_12px_rgba(217,56,84,0.12)] transition-[background-color,border-color,box-shadow] duration-200 disabled:opacity-40 disabled:cursor-not-allowed';

export const CHAT_TOOLBAR_BTN = `${CHAT_SECONDARY_BTN} flex items-center flex-shrink-0`;

export const CHAT_ICON_BTN = `${CHAT_SECONDARY_BTN} flex items-center justify-center flex-shrink-0`;

/** Header / in-thread secondary — no bordered pill chrome */
export const CHAT_GHOST_BTN =
  'inline-flex items-center justify-center gap-1.5 rounded-lg px-2.5 py-2 text-sm text-[#dadada] hover:text-white hover:bg-white/8 transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0';

export const CHAT_GHOST_ICON_BTN =
  'inline-flex items-center justify-center w-9 h-9 rounded-lg text-[#b5b5b5] hover:text-white hover:bg-white/8 transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0';

export const CHAT_TEXT_BTN =
  'inline-flex items-center gap-1 text-xs font-medium text-[#d93854] hover:text-white transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed';

export const CHAT_SEND_BTN =
  'inline-flex items-center justify-center w-11 h-11 rounded-xl bg-[#d93854] text-white hover:bg-[#c52a45] transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0';
