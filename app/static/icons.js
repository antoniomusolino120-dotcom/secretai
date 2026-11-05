/* Shared outline icons: one size, stroke and alignment across the dashboard. */
'use strict';
function uiIcon(name){
 const paths={
 overview:'<path d="M4 7h9m4 0h3M4 17h3m4 0h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
 services:'<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h4"/>',
 appointments:'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18m-13 4h2m4 0h2"/>',
 inbox:'<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2v-9.5A8.5 8.5 0 0 1 10.5 4h2a8.5 8.5 0 0 1 8.5 7.5Z"/><path d="M7 12h10m-10 4h6"/>',
 voice:'<path d="m8 3 3 5-3 3a14 14 0 0 0 5 5l3-3 5 3v3a2 2 0 0 1-2 2A18 18 0 0 1 3 5a2 2 0 0 1 2-2Z"/>',
 email:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4 7 8 6 8-6"/>',
 web:'<rect x="3" y="4" width="18" height="14" rx="3"/><path d="M8 22h8m-4-4v4m-5-11h10"/>',
 power:'<path d="M12 3v9m-5-7a8 8 0 1 0 10 0"/>',
 settings:'<path d="M4 7h9m4 0h3M4 17h3m4 0h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
 arrow:'<path d="m9 5 7 7-7 7"/>',
 browser:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18m-13 5h8"/>',
 };
 return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths[name]||paths.settings}</svg>`;
}
function channelLogo(channel){return ['whatsapp','instagram','googlecalendar'].includes(channel)?`<span class="channel-logo brand-${channel}" aria-hidden="true"><span></span></span>`:`<span class="channel-logo brand-${channel}" aria-hidden="true">${uiIcon(channel)}</span>`}
