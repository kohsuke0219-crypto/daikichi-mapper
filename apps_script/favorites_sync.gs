/**
 * 買取大吉 商圏マップ — 共有バックエンド Google Apps Script Webアプリ
 *
 * 1つのスプレッドシートで2種類のデータを共有する:
 *   - お気に入り地点      → "favorites" シート
 *   - NGエリア(出店しない) → "ng_areas" シート
 *
 *   GET  ?kind=favorites (既定) / ?kind=ng        … 一覧を返す
 *   POST { kind:'favorites'|'ng', action, token, ... } … 追加/更新/削除
 *     favorites: action='add'|'update'|'delete'（itemまたはid）
 *     ng:        action='add'|'delete'（itemまたはcode）
 *
 * 【貼り方】共有用スプレッドシートを開く → 拡張機能 > Apps Script → 全文を貼り付け。
 * 【デプロイ】デプロイ > 新しいデプロイ > ウェブアプリ
 *     実行ユーザー=自分 / アクセス=全員。表示URL(.../exec)を地図の⚙共有設定へ。
 *   ※コード更新後は「デプロイを管理 > 編集 > 新バージョン > デプロイ」で反映（URL不変）。
 *
 * 【注意】「全員」公開のためURLを知れば誰でも読み書き可能。URLはチーム内のみで共有。
 *         TOKEN を設定すると書き込み時に合言葉照合（地図のトークン欄と一致させる）。
 */

const TOKEN = '';   // 任意。設定したら地図の「トークン」欄にも同じ値を入れる。空なら無認証。

const FAV_SHEET   = 'favorites';
const FAV_HEADERS = ['id', 'lat', 'lng', 'comment', 'author', 'createdAt', 'updatedAt'];
const NG_SHEET    = 'ng_areas';
const NG_HEADERS  = ['code', 'city', 'pref', 'author', 'createdAt'];

function sheet_(name, headers) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();        // コンテナバインド(推奨)
  // const ss = SpreadsheetApp.openById('スプレッドシートID'); // スタンドアロンはこちら
  let sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); sh.appendRow(headers); }
  if (sh.getLastRow() === 0) sh.appendRow(headers);
  return sh;
}

function readAll_(sh) {
  const values = sh.getDataRange().getValues();
  const head = values.shift() || [];
  return values
    .filter(function (r) { return r[0] !== '' && r[0] != null; })
    .map(function (r) {
      const o = {};
      head.forEach(function (h, i) { o[h] = r[i]; });
      return o;
    });
}

// 1列目(キー)で行番号を探す。numeric=trueなら数値比較(市区町村コードの先頭ゼロ対策)。
function findRow_(sh, key, numeric) {
  const last = Math.max(sh.getLastRow(), 1);
  const col = sh.getRange(1, 1, last, 1).getValues();
  for (let i = 1; i < col.length; i++) {
    const cell = col[i][0];
    const hit = numeric ? (Number(cell) === Number(key)) : (String(cell) === String(key));
    if (hit) return i + 1;
  }
  return -1;
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  const kind = (e && e.parameter && e.parameter.kind) || 'favorites';
  if (kind === 'ng') return json_(readAll_(sheet_(NG_SHEET, NG_HEADERS)));
  return json_(readAll_(sheet_(FAV_SHEET, FAV_HEADERS)));
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    if (TOKEN && body.token !== TOKEN) {
      return json_({ ok: false, error: 'unauthorized' });
    }
    const kind = body.kind || 'favorites';
    const action = body.action;
    const now = new Date().toISOString();

    if (kind === 'ng') {
      const sh = sheet_(NG_SHEET, NG_HEADERS);
      if (action === 'add') {
        const it = body.item || {};
        if (findRow_(sh, it.code, true) < 0) {  // 重複コードは追加しない
          sh.appendRow([String(it.code), it.city || '', it.pref || '', it.author || '', it.createdAt || now]);
        }
      } else if (action === 'delete') {
        const row = findRow_(sh, body.code, true);
        if (row > 0) sh.deleteRow(row);
      } else {
        return json_({ ok: false, error: 'unknown ng action' });
      }
      return json_({ ok: true, items: readAll_(sh) });
    }

    // ----- favorites -----
    const sh = sheet_(FAV_SHEET, FAV_HEADERS);
    if (action === 'add') {
      const it = body.item || {};
      sh.appendRow([
        String(it.id), Number(it.lat), Number(it.lng),
        it.comment || '', it.author || '',
        it.createdAt || now, it.updatedAt || now,
      ]);
    } else if (action === 'update') {
      const it = body.item || {};
      const row = findRow_(sh, it.id, false);
      if (row > 0) {
        sh.getRange(row, 4).setValue(it.comment || '');     // comment列
        sh.getRange(row, 7).setValue(it.updatedAt || now);  // updatedAt列
      }
    } else if (action === 'delete') {
      const row = findRow_(sh, body.id, false);
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
