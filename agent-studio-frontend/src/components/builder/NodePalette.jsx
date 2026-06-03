import { APP_DATA } from '@/data/appData';
import { getPaletteIconBg } from './nodeCategoryStyles';
import { COLOR, FONT, PALETTE } from './figmaSpec';
import { useFigmaPx } from './useFigmaScale';
import AppIcon from '../ui/AppIcon';

// Figma "Left Panel" 86:2498 — w 226, p 16, gap 20, rounded 16, bg #1a1a1a.
// Items list 86:2500 — gap 8.  Each item 86:2501 — gap 12, items-center.
// Icon tile 86:2502 — 32×32 (24px icon + 4px padding all sides), rounded 8.
// Every dimension here is the Figma value at the 1920px reference width;
// the `px(value)` helper rescales them for the actual viewport.

export default function NodePalette() {
  const { px } = useFigmaPx();

  const handleDragStart = (e, node) => {
    e.dataTransfer.setData('application/json', JSON.stringify(node));
    e.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <div
      className="absolute left-4 z-10 transition-all duration-300 flex flex-col flex-shrink-0 overflow-y-auto"
      style={{
        top: px(16),
        width: px(PALETTE.width),
        maxHeight: 'calc(100vh - 220px)',
        backgroundColor: COLOR.darkest,
        padding: px(PALETTE.padding),
        gap: px(PALETTE.gap),
        borderRadius: px(PALETTE.radius),
      }}
    >
      <h3
        style={{
          color: COLOR.white,
          fontSize: px(FONT.subhead2Bold.size),
          lineHeight: `${px(FONT.subhead2Bold.height)}px`,
          fontWeight: FONT.subhead2Bold.weight,
        }}
      >
        Nodes
      </h3>

      <div className="flex flex-col" style={{ gap: px(PALETTE.itemListGap) }}>
        {APP_DATA.nodeTypes.map((category) => {
          const visibleNodes = category.nodes.filter((node) => !node.hiddenFromPalette);
          if (visibleNodes.length === 0) return null;

          return (
          <div key={category.category || 'top'} className="flex flex-col" style={{ gap: px(PALETTE.itemListGap) }}>
            {category.category && (
              <span
                className="uppercase"
                style={{
                  color: COLOR.medium,
                  fontSize: px(FONT.body3.size),
                  lineHeight: `${px(FONT.body3.height)}px`,
                  fontWeight: FONT.body3.weight,
                }}
              >
                {category.category}
              </span>
            )}

            {visibleNodes.map((node) => (
              <div
                key={node.id}
                draggable
                onDragStart={(e) => handleDragStart(e, node)}
                className="group flex items-center cursor-grab active:cursor-grabbing transition-colors duration-150 hover:bg-white/5 rounded-md"
                style={{
                  gap: px(PALETTE.item.gap),
                  paddingLeft: px(4),
                  paddingRight: px(4),
                  paddingTop: px(4),
                  paddingBottom: px(4),
                  marginLeft: px(-4),
                  marginRight: px(-4),
                }}
                title={node.description}
              >
                <span
                  className="flex items-center justify-center flex-shrink-0"
                  style={{
                    width: px(PALETTE.iconTile.size),
                    height: px(PALETTE.iconTile.size),
                    padding: px(PALETTE.iconTile.padding),
                    borderRadius: px(PALETTE.iconTile.radius),
                    backgroundColor: getPaletteIconBg(node.id),
                  }}
                >
                  {node.icon?.startsWith('/') ? (
                    <AppIcon
                      src={node.icon}
                      size={px(PALETTE.iconTile.innerIcon)}
                      color={COLOR.white}
                      weight="regular"
                    />
                  ) : (
                    <span style={{ color: COLOR.white, fontSize: px(FONT.body2.size) }}>{node.icon}</span>
                  )}
                </span>
                <span
                  className="truncate flex-1 min-w-0"
                  style={{
                    color: COLOR.white,
                    fontSize: px(FONT.body2.size),
                    lineHeight: `${px(FONT.body2.height)}px`,
                    fontWeight: FONT.body2.weight,
                  }}
                >
                  {node.name}
                </span>
              </div>
            ))}
          </div>
          );
        })}
      </div>
    </div>
  );
}
