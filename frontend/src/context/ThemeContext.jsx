import React, { createContext, useContext, useLayoutEffect, useState } from "react";

const ThemeContext = createContext(null);

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem("okd-theme") === "light" ? "light" : "dark";
  });

  useLayoutEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("okd-theme", theme);
  }, [theme]);

  const toggleTheme = () => {
    document.documentElement.classList.add("theme-transitioning");
    setTheme((t) => (t === "dark" ? "light" : "dark"));
    window.setTimeout(
      () => document.documentElement.classList.remove("theme-transitioning"),
      300
    );
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
