import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid(defineConfig({
  title: 'MIVAIS',
  description: 'Mixed-Initiative Visual Analytics Infrastructure System — a governance layer for collaborative, multi-agent visual analytics systems.',

  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/logo.svg' }],
    ['meta', { name: 'theme-color', content: '#1e6fc7' }],
  ],

  themeConfig: {
    siteTitle: 'MIVAIS',

    nav: [
      { text: 'Guide', link: '/guide/introduction' },
      { text: 'API Reference', link: '/api/overview' },
      { text: 'Grammars', link: '/reference/grammars' },
    ],

    sidebar: {
      '/guide/': [
        {
          text: 'Guide',
          items: [
            { text: 'Introduction',       link: '/guide/introduction' },
            { text: 'Core Concepts',      link: '/guide/concepts' },
            { text: 'Building a System',  link: '/guide/building' },
            { text: 'Configuration',      link: '/guide/configuration' },
          ],
        },
      ],
      '/api/': [
        {
          text: 'API Reference',
          items: [
            { text: 'Overview',          link: '/api/overview' },
          ],
        },
        {
          text: 'Infrastructure',
          items: [
            { text: 'WorldState',        link: '/api/world-state' },
            { text: 'MessageBus',        link: '/api/message-bus' },
            { text: 'AgentRegistry',     link: '/api/agent-registry' },
            { text: 'PermissionGuard',   link: '/api/permission-guard' },
            { text: 'AuditLog',          link: '/api/audit-log' },
            { text: 'Gateway',           link: '/api/gateway' },
            { text: 'SessionRecorder',   link: '/api/session-recorder' },
            { text: 'Rooms',             link: '/api/rooms' },
          ],
        },
        {
          text: 'Agents',
          items: [
            { text: 'BaseAgent',         link: '/api/base-agent' },
          ],
        },
      ],
      '/reference/': [
        {
          text: 'Reference',
          items: [
            { text: 'Configuration Grammars (EBNF)', link: '/reference/grammars' },
          ],
        },
      ],
    },

    search: { provider: 'local' },

    outline: { level: [2, 3] },

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'MIVAIS — Mixed-Initiative Visual Analytics Infrastructure System',
    },
  },

  markdown: {
    theme: { light: 'github-light', dark: 'github-dark' },
  },

  mermaid: {
    theme: 'default',
  },
}))
