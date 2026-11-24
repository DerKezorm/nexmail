// ESLint following the Vite template for React and TypeScript, like in nexnotes.
//
// Warning: the threshold is set to zero: `npm run lint` calls `eslint . --max-warnings 0`.
// ESLint returns exit code 0 for plain warnings; without a threshold this
// step would be a check that never triggers.
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  // The shared modules (sign-in, accounts, mail) come unchanged from bauplaene and are linted there.
  { ignores: ['**/dist/**', 'src/vendor/**', 'test-results/**', 'playwright-report/**'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', destructuredArrayIgnorePattern: '^_' },
      ],
      // Like in Nexview: pre-filling draft state from a query is the
      // pattern used by all settings pages.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/refs': 'off',
      // nexmail: the React Compiler is not used in the build; its rules about memoisation and about values declared
      // later in a component (read only in callbacks that run after the render) say nothing about this code.
      'react-hooks/preserve-manual-memoization': 'off',
      'react-hooks/immutability': 'off',
      'react-hooks/use-memo': 'off',
      // nexmail keeps small helpers next to the component that uses them; fast refresh is a matter of the dev server.
      'react-refresh/only-export-components': 'off',
    },
  },
)
