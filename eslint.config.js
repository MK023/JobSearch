import globals from "globals";

export default [
  {
    files: ["frontend/static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: "script",
      globals: {
        ...globals.browser,

        // Alpine.js (loaded via CDN in base.html)
        Alpine: "readonly",
        $data: "readonly",
        $refs: "readonly",
        $el: "readonly",
        $watch: "readonly",
        $dispatch: "readonly",
        $nextTick: "readonly",
        $store: "readonly",

        // Chart.js (loaded via CDN on stats page)
        Chart: "readonly",

        // Flatpickr (loaded via CDN on interview page)
        flatpickr: "readonly",

        // Cross-file global functions — "writable" because each file
        // defines some and consumes others via separate <script> tags.
        showToast: "writable",
        fetchJSON: "writable",
        handleRateLimit: "writable",
        refreshSpending: "writable",
        initBudgetEditing: "writable",
        initCVUpload: "writable",
        refreshHistoryCounts: "writable",
        app: "writable",
        toggleTheme: "writable",
        submitAnalysis: "writable",
        resetLoading: "writable",
        historyTabs: "writable",
        setStatus: "writable",
        deleteAnalysis: "writable",
        batchManager: "writable",
        toggleContacts: "writable",
        loadContacts: "writable",
        saveContact: "writable",
        deleteContact: "writable",
        genFollowup: "writable",
        genLinkedin: "writable",
        markFollowupDone: "writable",
        uploadCV: "writable",
        cleanupForm: "writable",
        bulkRejectForm: "writable",
        aiPreferences: "writable",
        togglePlatformFields: "writable",
        openInterviewModal: "writable",
        openNewRoundModal: "writable",
        closeInterviewModal: "writable",
        submitInterview: "writable",
        deleteInterviewFromDetail: "writable",
        logRoundOutcome: "writable",
        markAsOffer: "writable",
        FileUpload: "writable",
        addTodoServer: "writable",
        toggleTodo: "writable",
        removeTodo: "writable",
      },
    },
    rules: {
      // --- Possible errors (catch real bugs) ---
      "no-undef": "error",
      "no-dupe-keys": "error",
      "no-dupe-args": "error",
      "no-duplicate-case": "error",
      "no-unreachable": "error",
      "no-constant-condition": "warn",
      "no-empty": "warn",
      "no-extra-semi": "warn",
      "no-func-assign": "error",
      "no-inner-declarations": "error",
      "no-irregular-whitespace": "error",
      "no-sparse-arrays": "warn",
      "valid-typeof": "error",
      "no-unexpected-multiline": "error",

      // --- Best practices (catch likely mistakes) ---
      "no-self-assign": "error",
      "no-self-compare": "error",
      // Disabled: cross-file globals pattern causes false positives.
      // Each file defines functions that other files consume via <script> tags.
      "no-redeclare": "off",
      "use-isnan": "error",
      "eqeqeq": ["warn", "smart"],

      // --- Variables ---
      "no-unused-vars": ["warn", {
        args: "none",
        caughtErrors: "none",
        varsIgnorePattern: "^_",
      }],
      "no-shadow-restricted-names": "error",

      // --- ES6+ modernization (SonarCloud S3504 + S6582) ---
      // "var" has function-scope quirks and hoisting footguns; prefer block-scoped.
      "no-var": "error",
      "prefer-const": ["error", { destructuring: "any" }],
    },
  },
  {
    // Chrome extension — isolated runtime, chrome.* globals, no CDN libs.
    files: ["frontend/chrome-extension/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        chrome: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["warn", {
        args: "none",
        caughtErrors: "none",
        varsIgnorePattern: "^_",
      }],
      "no-shadow-restricted-names": "error",
      "eqeqeq": ["warn", "smart"],
      "no-self-assign": "error",
      "no-self-compare": "error",
      "use-isnan": "error",
      "no-var": "error",
      "prefer-const": ["error", { destructuring: "any" }],
    },
  },
];
