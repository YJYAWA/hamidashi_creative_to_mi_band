// 说话人显示名归一（日文/异体 -> 简体）
const DISPLAY_NAMES = {
  '妃愛のマネージャー': '妃爱的经纪人',
  'おばあちゃん': '外婆',
  '妃愛': '妃爱',
  '華乃': '华乃',
  '錦': '锦',
  'あすみ': '明日美',
}

export function toDisplayCharacterName(name) {
  const key = String(name || '')
  return Object.prototype.hasOwnProperty.call(DISPLAY_NAMES, key) ? DISPLAY_NAMES[key] : key
}

export default { toDisplayCharacterName }
