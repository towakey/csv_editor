# csv_editor

CSVをブラウザで編集し、承認者の確認後に実ファイルへ反映するCGIアプリです。

## 承認フロー設定

`setting.json` に次を設定してください。

- 各ユーザーの `email`
- 各ファイルの `approver_usernames`
- `approval.review_url`: 外部から開ける `approval_review.py` のHTTPS URL
- `approval.smtp`: SMTP接続先、送信元、TLS設定

SMTPパスワードは `setting.json` へ保存せず、既定では環境変数
`CSV_EDITOR_SMTP_PASSWORD` に設定します。接続先、ユーザー名、送信元も
`CSV_EDITOR_SMTP_HOST`、`CSV_EDITOR_SMTP_USERNAME`、
`CSV_EDITOR_SMTP_FROM` で上書きできます。

`approval.review_url` を空にした場合は、確認依頼時のHTTPホストと
`SCRIPT_NAME` から確認URLを組み立てます。リバースプロキシ配下では公開URLを
明示することを推奨します。

## 動作

1. 作業者がCSVを編集して「確認依頼」を押す
2. 変更内容が `approval.draft_directory` に下書き保存され、承認者へメール送信される
3. 承認者がメールのリンクで差分を確認し、承認または却下する
4. 承認時だけバックアップ・変更履歴を作成して実ファイルへ反映する
5. 却下時は作業者へ理由をメール通知し、編集画面から下書きを復元できる

依頼後に実ファイルが別の処理で変わった場合、その依頼は承認できません。
作業者が最新ファイルを開き直して再依頼してください。
