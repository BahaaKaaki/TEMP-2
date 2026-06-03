import { forwardRef } from 'react';
import { LOGIN_RAYS } from './loginRaysData';

/**
 * ApexLoginRays — radial streaming light bundle for the login page.
 *
 * Each ray is a thin absolutely-positioned div anchored at the (originX,
 * originY) viewport coordinates and rotated to its angle. The inner streak
 * animates via `transform: scaleX` + `translateX` so motion stays on the
 * GPU compositor (no paint, no layout). Length is set to the viewport
 * diagonal so every ray exits the screen no matter where the origin sits.
 */
const ApexLoginRays = forwardRef(function ApexLoginRays(
  { originX = 0, originY = 0 },
  ref,
) {
  return (
    <div
      ref={ref}
      className="login-page__rays"
      style={{ '--ray-origin-x': `${originX}px`, '--ray-origin-y': `${originY}px` }}
      aria-hidden="true"
    >
      <div className="login-page__rays-bundle">
        {LOGIN_RAYS.map((ray) => (
          <div
            key={ray.id}
            className="login-page__ray"
            style={{
              '--ray-angle': `${ray.angle}deg`,
              '--ray-width': `${ray.width}px`,
              '--ray-opacity': ray.opacity,
              '--ray-duration': `${ray.duration}s`,
              '--ray-delay': `${ray.delay}s`,
            }}
          >
            <span className="login-page__ray-streak" />
          </div>
        ))}
      </div>
    </div>
  );
});

export default ApexLoginRays;
