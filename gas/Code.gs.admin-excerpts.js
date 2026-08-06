/* ═══════════════════════════════════════════════════════════════
 * Code.gs 발췌 보관 (v2.9 기준, 2026-08-06 대표 전달 사본에서 추출)
 * 관리자 대시보드 개선에서 참조/수정 가능성이 있는 서버 함수만 보관.
 * 전체 Code.gs는 대표가 필요 시 다시 전달 가능.
 *
 * buildAdminPayload_() 반환 키:
 *   token, books[], issues[], engineers[], reviewers[], actors[],
 *   verdicts, maxMB, baseUrl, sheetUrls, alerts (=adminAlerts_(issues)),
 *   stages, roles, prod (readProdForAdmin_()), partners, casting, samples,
 *   apiKey, attendance, alertLog (=alertLogForAdmin_()), work, verdictHelp,
 *   recLog, recMethods
 *
 * books[] 항목: group, sort, title, abbr, pub, stage, due, eng, reviewer,
 *   rt, folderUrl, msUrl, origUrl, recUrl, refUrl, qaUrl, pubqaUrl,
 *   finalUrl, pdbTitle, reqNote, toneNote, titleNote, trailerNote,
 *   editDue, music, rtEst, cast[]
 *
 * prod.rows[] 항목: pid, pub, title, step(1..10), deadline(M/d),
 *   checks[{key,label,done,due}], pendingCnt, memo
 * ═══════════════════════════════════════════════════════════════ */

/** 지금 대표님이 확인·판단해야 할 일들만 모아 알림 목록으로 반환.
 *  kind: pub(출판사 제출) / rec(성우 재녹음 도착) / wait(판정 대기)
 *  v2.2.1: 출판사 체크 항목의 "기한 임박·경과"는 알림에서 뺐습니다 —
 *  도서 수만큼 항목별로 쌓여(도서당 최대 4건) 정작 확인해야 할 제출·판정 알림이
 *  묻히는 문제가 있었습니다. 기한은 각 도서 카드의 체크 항목 색상·D-day 표시로 계속 보실 수 있습니다. */
function adminAlerts_(issues) {
  const out = [];
  // 1) 출판사가 등록한 초안 검수 피드백 중 아직 판정 전
  (issues || []).forEach(i => {
    const isPub = String(i.stage || '').indexOf('출판사') >= 0;
    const waiting = !i.verdict || i.verdict === '대기';
    if (isPub && waiting) {
      out.push({ kind: 'pub', book: i.book, id: i.id,
        text: '출판사 초안 검수 등록 — 판정 필요',
        detail: [i.file, i.time, (i.err || i.line || '').slice(0, 40)].filter(Boolean).join(' · ') });
    } else if (waiting && !isPub) {
      out.push({ kind: 'wait', book: i.book, id: i.id,
        text: '판정 대기',
        detail: [i.file, i.time, (i.err || i.line || '').slice(0, 40)].filter(Boolean).join(' · ') });
    }
    // 2) 성우 재녹음 파일이 도착했는데 아직 반영 처리 전
    if (i.recstat === '업로드완료' && String(i.applied || '').trim() !== '반영완료') {
      out.push({ kind: 'rec', book: i.book, id: i.id,
        text: '재녹음 도착 — 반영 처리 필요',
        detail: [i.actor, i.upTime].filter(Boolean).join(' · ') });
    }
  });
  return out;
}

function alertLogForAdmin_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(CFG.SH.ALOG);
  if (!sh || sh.getLastRow() < 2) return [];
  const out = [];
  sh.getRange(2, 1, sh.getLastRow() - 1, 7).getValues().forEach(v => {
    if (!String(v[0] || '').trim()) return;
    if (String(v[6] || '').trim()) return; // 확인됨
    const dt = (v[1] && v[1].getTime) ? v[1] : null;
    out.push({ id: String(v[0]), time: dt ? Utilities.formatDate(dt, CFG.TZ, 'M/d HH:mm') : '',
      kind: String(v[2] || ''), book: String(v[3] || ''), pub: String(v[4] || ''), text: String(v[5] || '') });
  });
  out.reverse();
  return out.slice(0, 50);
}
