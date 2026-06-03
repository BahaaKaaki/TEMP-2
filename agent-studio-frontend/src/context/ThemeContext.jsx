import { createContext, useContext, useEffect } from 'react';

const ThemeContext = createContext();

export function ThemeProvider({ children }) {
  // Always use light mode - dark mode is disabled
  const theme = 'light';

  useEffect(() => {
    // Apply light theme to document
    document.documentElement.setAttribute('data-color-scheme', 'light');
    // Ensure dark class is never applied
    document.documentElement.classList.remove('dark');
  }, []);

  // toggleTheme is a no-op since dark mode is disabled
  const toggleTheme = () => {};

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
