import { ICON_REGISTRY, resolveIconName } from './iconRegistry';

/**
 * Shared Phosphor icon wrapper — replaces masked `/icons/*.svg` sprites
 * with a consistent, less generic icon set (@phosphor-icons/react).
 */
export default function AppIcon({
  name,
  src,
  size = 24,
  weight = 'regular',
  color = 'currentColor',
  className,
  style,
  'aria-hidden': ariaHidden = true,
}) {
  const resolved = resolveIconName(name ?? src);
  const Icon = resolved ? ICON_REGISTRY[resolved] : null;

  if (!Icon) return null;

  return (
    <Icon
      size={size}
      weight={weight}
      color={color}
      className={className}
      style={{ flexShrink: 0, ...style }}
      aria-hidden={ariaHidden}
    />
  );
}
