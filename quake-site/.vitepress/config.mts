import { defineConfig } from 'vitepress'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Icons are the Mesh America design system's Untitled UI line icons, inlined so they follow
// currentColor (and so the light and dark themes both work).
const iconDir = fileURLToPath(new URL('./theme/icons/', import.meta.url))
const icon = (name: string) =>
  readFileSync(`${iconDir}${name}.svg`, 'utf-8').replace(/\s(width|height)="24"/g, '')

const REPO = 'https://github.com/Mesh-America/mesh-america-quake-repeater'

export default defineConfig({
  title: 'Quake Repeater',
  description:
    'A LoRa mesh repeater that feels the ground move: it posts a short earthquake alert to your mesh channel, with no internet needed.',
  lang: 'en-US',
  base: '/',
  srcDir: 'src',
  cleanUrls: true,
  appearance: 'dark',
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/emblem-dark.svg' }],
    ['meta', { name: 'theme-color', content: '#0a1220' }],
  ],

  themeConfig: {
    logo: { light: '/emblem-light.svg', dark: '/emblem-dark.svg', alt: '' },
    siteTitle: 'Quake Repeater',

    nav: [
      { text: 'Home', link: '/' },
      { text: 'Get started', link: '/getting-started' },
      { text: 'Hardware', link: '/hardware' },
      { text: 'Admin guide', link: '/admin-guide' },
      { text: 'Docs', link: '/earthquake-alerts' },
      { text: 'Flasher', link: 'https://apps.meshamerica.com/quake-repeater/' },
      { text: 'GitHub', link: REPO },
      { text: 'Mesh America', link: 'https://meshamerica.com' },
      { text: 'Pitch In', link: 'https://meshamerica.com/pitch-in/' },
    ],

    sidebar: [
      {
        text: 'Get started',
        items: [
          { text: 'Supported hardware', link: '/hardware' },
          { text: 'Flash and set up', link: '/getting-started' },
          { text: 'How to admin your repeater', link: '/admin-guide' },
          { text: 'Update over the air (OTA)', link: '/ota-updates' },
        ],
      },
      {
        text: 'Understanding alerts',
        items: [
          { text: 'Earthquake channel alerts', link: '/earthquake-alerts' },
          { text: 'What the sensor readings mean', link: '/reading-the-sensor' },
        ],
      },
      {
        text: 'Reference',
        items: [
          { text: "The repeater's clock", link: '/clock-floor' },
          { text: 'D7S sensor integration', link: '/d7s-integration' },
          { text: 'Measurement contract', link: '/d7s-measurement-contract' },
        ],
      },
    ],

    socialLinks: [{ icon: 'github', link: REPO }],
    search: { provider: 'local' },
    outline: { level: [2, 3], label: 'On this page' },
    editLink: {
      pattern: `${REPO}/edit/next/docs/:path`,
      text: 'Edit this page on GitHub',
    },
    footer: {
      message:
        'Brought to you by <a href="https://meshamerica.com">Mesh America</a>. When the internet goes down, the mesh stays up.',
      copyright: 'MIT licensed, with upstream MeshCore and Keymind Cascade notices retained.',
    },
  },

  // The home page names its feature icons (iconName); this swaps in the inline SVG.
  transformPageData(pageData) {
    if (pageData.relativePath === 'index.md' && pageData.frontmatter.features) {
      for (const f of pageData.frontmatter.features) {
        if (typeof f.iconName === 'string') f.icon = icon(f.iconName)
      }
    }
  },
})
