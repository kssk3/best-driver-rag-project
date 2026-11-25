// Exact code excerpts observed in the previous HTTP response; not full raw response bytes.
const TRASH_GROUPS={ MWF:{label:'월·수·금',color:'#2563eb'}, TWS:{label:'화·목·일',color:'#f97316'}, APT:{label:'아파트 매일 배출',color:'#7c3aed'} };
const TRASH_RECYCLE={ MWF:{etc:'월·수',petv:'금'}, TWS:{etc:'화·목',petv:'일'} };
// openSheetTrash(dong) uses these entries in the rendered sheet:
const r=TRASH_RECYCLE[g];
// Rows passed into trashTable:
[['종량제·음식물',TRASH_GROUPS[g].label],['기타 재활용품',r.etc],['투명페트병·비닐',r.petv]]
