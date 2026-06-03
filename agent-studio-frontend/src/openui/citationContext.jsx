import { createContext, useContext } from 'react';

const OpenUICitationContext = createContext([]);

export function OpenUICitationProvider({ citations, children }) {
  return (
    <OpenUICitationContext.Provider value={Array.isArray(citations) ? citations : []}>
      {children}
    </OpenUICitationContext.Provider>
  );
}

export function useOpenUICitations() {
  return useContext(OpenUICitationContext);
}
