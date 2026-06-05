/**
 * 買取大吉 商圏マップ — お気に入り共有 Google Apps Script Webアプリ
 *
 * スプレッドシートに "favorites" シートを作り、お気に入り地点を保存・共有する。
 *   GET  : 全件取得（JSON配列）
 *   POST : { action: 'add'|'update'|'delete', token, item|id }
 *
 * 【使い方】このコードを貼る方法は2通り（どちらでも可）:
 *   (A) コンテナバインド（推奨・簡単）:
 *       共有用スプレッドシートを開く → 拡張機能 > Apps Script → このコードを貼る。
 *       getSheet_() は getActiveSpreadsheet() を使うのでそのままでOK。
 *   (B) スタンドアロン:
 *       SHEET_ID に対象スプレッドシートIDを入れ、getSheet_() を openById に切替（下記コメント参照）。
 *
 * 【デプロイ】デプロイ > 新しいデプロイ > 種類「ウェブアプリ」
 *   - 実行するユーザー : 自分
 *   - アクセスできるユーザー : 全員（Anyone）  ← ログイン無しの fetch に必要
 *   デプロイ後に表示される「ウェブアプリのURL（.../exec）」を地図の ⚙共有設定 に貼る。
 *
 * 【セキュリティ注意】
 *   - 「全員」公開なのでURLを知っていれば誰でも読み書き可能。URLはチーム内のみで共有すること。
 *   - 簡易的な書き込み保護として TOKEN を設定可能（地図側「トークン」と一致させる）。
 *     ※TOKENもURLと一緒に共有する前提なので強固な認証ではない（内部利用向けの抑止）。
 */

const SHEET_NAME = 'favorites';
const TOKEN = '';   // 任意。設定したら地図の「トークン」欄にも同じ値を入れる。空なら無認証。
const HEADERS = ['id', 'lat', 'lng', 'comment', 'author', 'createdAt', 'updatedAt'];

// (B)スタンドアロンにする場合のみ使用
// const SHEET_ID = 'ここにスプレッドシートIDを入れる';

function getSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();        // (A)コンテナバインド
  // const ss = SpreadsheetApp.openById(SHEET_ID);          // (B)スタンドアロンはこちらに切替
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) { sh = ss.insertSheet(SHEET_NAME); sh.appendRow(HEADERS); }
  if (sh.getLastRow() === 0) sh.appendRow(HEADERS);
  return sh;
}

function readAll_(sh) {
  const values = sh.getDataRange().getValues();
  const head = values.shift() || HEADERS;
  return values
    .filter(function (r) { return r[0] !== '' && r[0] != null; })
    .map(function (r) {
      const o = {};
      head.forEach(function (h, i) { o[h] = r[i]; });
      o.id = String(o.id);
      o.lat = Number(o.lat);
      o.lng = Number(o.lng);
      o.comment = o.comment == null ? '' : String(o.comment);
      return o;
    });
}

function findRow_(sh, id) {
  const last = Math.max(sh.getLastRow(), 1);
  const ids = sh.getRange(1, 1, last, 1).getValues();
  for (let i = 1; i < ids.length; i++) {
    if (String(ids[i][0]) === String(id)) return i + 1;  // 1始まりの行番号
  }
  return -1;
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return json_(readAll_(getSheet_()));
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    if (TOKEN && body.token !== TOKEN) {
      return json_({ ok: false, error: 'unauthorized' });
    }
    const sh = getSheet_();
    const action = body.action;
    const now = new Date().toISOString();

    if (action === 'add') {
      const it = body.item || {};
      sh.appendRow([
        String(it.id), Number(it.lat), Number(it.lng),
        it.comment || '', it.author || '',
        it.createdAt || now, it.updatedAt || now,
      ]);
    } else if (action === 'update') {
      const it = body.item || {};
      const row = findRow_(sh, it.id);
      if (row > 0) {
        sh.getRange(row, 4).setValue(it.comment || '');          // comment列
        sh.getRange(row, 7).setValue(it.updatedAt || now);       // updatedAt列
      }
    } else if (action === 'delete') {
      const row = findRow_(sh, body.id);
      if (row > 0) sh.deleteRow(row);
    } else {
      return json_({ ok: false, error: 'unknown action' });
    }
    return json_({ ok: true, items: readAll_(sh) });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}
