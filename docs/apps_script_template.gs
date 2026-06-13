/**
 * 주간 요약 수신용 Apps Script 웹앱 (설계 문서 4장).
 * summary.py 가 POST 하는 JSON을 받아 스프레드시트에 기록한다.
 *
 * 배포: 확장 프로그램 > Apps Script > 배포 > 새 배포 > 유형: 웹 앱
 *   - 실행 계정: 나(spmediatek)
 *   - 액세스: 모든 사용자
 * 배포 URL을 GitHub 저장소 Secret `SHEETS_WEBHOOK_URL` 에 등록한다.
 *
 * 시트 구성: 'Summary' 탭에 매주 누적 기록. 전체 데이터는 넣지 않는다(셀 한도).
 */
function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName('Summary') || ss.insertSheet('Summary');

    if (sheet.getLastRow() === 0) {
      sheet.appendRow(['generated_at', 'platform', 'chart', 'date',
                       'rank', 'title', 'author', 'new_entry']);
    }

    var gen = payload.generated_at;
    (payload.charts || []).forEach(function (c) {
      var newSet = {};
      (c.new_entries || []).forEach(function (t) { newSet[t] = true; });
      (c.top || []).forEach(function (row) {
        sheet.appendRow([gen, c.platform, c.chart, c.date,
                         row.rank, row.title, row.author,
                         newSet[row.title] ? 'NEW' : '']);
      });
    });

    return ContentService
      .createTextOutput(JSON.stringify({ ok: true, charts: (payload.charts || []).length }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
