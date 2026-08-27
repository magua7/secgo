import type { SVGProps } from 'react'

const paths: Record<string, React.ReactNode> = {
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41"/></>,
  moon: <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.34 1.88l.06.06-2.83 2.83-.06-.06a1.7 1.7 0 00-1.88-.34 1.7 1.7 0 00-1.03 1.56V21h-4v-.09A1.7 1.7 0 009 19.36a1.7 1.7 0 00-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 004.63 15 1.7 1.7 0 003.08 14H3v-4h.09A1.7 1.7 0 004.64 9a1.7 1.7 0 00-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 009 4.63 1.7 1.7 0 0010 3.08V3h4v.09A1.7 1.7 0 0015 4.64a1.7 1.7 0 001.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0019.37 9 1.7 1.7 0 0020.92 10H21v4h-.09A1.7 1.7 0 0019.4 15z"/></>,
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/></>,
  eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/></>,
  eyeOff: <><path d="M3 3l18 18M10.6 10.6a2 2 0 002.8 2.8M9.9 4.2A11 11 0 0112 4c6.5 0 10 8 10 8a18 18 0 01-2.1 3.1M6.6 6.6C3.7 8.4 2 12 2 12s3.5 8 10 8a10 10 0 004.1-.9"/></>,
  send: <><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  panel: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></>,
  close: <path d="M6 6l12 12M18 6L6 18"/>,
  chevron: <path d="M9 18l6-6-6-6"/>,
  search: <><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></>,
  stop: <rect x="6" y="6" width="12" height="12" rx="1"/>,
  paperclip: <path d="M21.4 11.6l-8.5 8.5a6 6 0 01-8.5-8.5l9.2-9.2a4 4 0 015.7 5.7l-9.2 9.2a2 2 0 01-2.8-2.8l8.5-8.5"/>,
  more: <><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></>,
  check: <path d="M20 6L9 17l-5-5"/>,
  domainShield: <><circle cx="10" cy="11" r="7"/><path d="M3 11h14M10 4c2 2 3 4.3 3 7M10 4c-2 2-3 4.3-3 7M10 18c-1.1-1.1-1.9-2.3-2.4-3.7M16 13l4-1.5 2 1v3.2c0 2.5-1.8 4.3-4 5.3-2.2-1-4-2.8-4-5.3v-3.2z"/></>,
  webScan: <><rect x="2.5" y="4" width="19" height="15" rx="2"/><path d="M2.5 8h19M7 6h.01M10 6h.01M8 13a4 4 0 018 0M12 13h3"/></>,
  iocRadar: <><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 4v3M20 12h-3M12 20v-3M4 12h3M12 12l5-5"/></>,
  sampleTrace: <><path d="M5 3h9l5 5v13H5zM14 3v5h5"/><circle cx="10" cy="13" r="2.5"/><path d="M12 15l3 3M15 18h4"/></>,
  cveShield: <><path d="M12 3l7 3v5c0 4.7-2.8 8.1-7 10-4.2-1.9-7-5.3-7-10V6z"/><path d="M9 10h6M10 7.5l1 2.5M14 7.5L13 10M9.5 13.5h5M12 10v6"/></>,
  aptNetwork: <><circle cx="12" cy="7" r="3"/><circle cx="5" cy="17" r="2.5"/><circle cx="19" cy="17" r="2.5"/><path d="M10 9.5L6.5 15M14 9.5l3.5 5M7.5 17h9"/></>,
  taskAnalysis: <><path d="M4 2h9l5 5v15H4zM13 2v5h5M7 10h7M7 14h4"/><circle cx="14.5" cy="16.5" r="3.5"/><path d="M17 19l3 3"/></>,
  agentCollaboration: <><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="7" r="2.5"/><circle cx="7" cy="17" r="2.5"/><circle cx="17" cy="17" r="2.5"/><path d="M9.5 7h5M7 9.5v5M17 9.5v5M9.5 17h5M8.8 8.8l6.4 6.4M15.2 8.8l-6.4 6.4"/></>,
  evidenceReport: <><path d="M4 2h9l5 5v15H4zM13 2v5h5M7 10h7M7 14h4"/><path d="M16 11.5l4 1.5v3c0 2.2-1.5 3.9-4 5-2.5-1.1-4-2.8-4-5v-3z"/><path d="M14.2 16l1.2 1.2 2.5-2.6"/></>,
  tool: <><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.8-3.8a1 1 0 000-1.4l-1.6-1.6a1 1 0 00-1.4 0L14.7 6.3z"/><path d="M4 20l5.5-5.5"/><path d="M15 4l5 5"/><path d="M4 20l3.5-3.5"/><circle cx="8" cy="8" r="3"/></>,
}

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: string }) {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name] ?? paths.chevron}</svg>
}