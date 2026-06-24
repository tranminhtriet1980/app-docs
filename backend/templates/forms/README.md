# Mẫu form Word (file output cần điền)

Đặt file `.docx` mẫu của bạn vào thư mục này **hoặc** upload trên web tại **Review → Upload mẫu form**.

## Cách tạo file mẫu Word

Trong file Word, chèn placeholder dạng:

```
{{identity.family_name}}
{{identity.given_names}}
{{passport.number}}
{{immigration.sevis_id}}
```

Hoặc dùng nhãn tiếng Anh (theo mapping):

```
{{Surname}}
{{Given Names}}
{{Passport Number}}
```

## Tên file & mã form

| Cách | Ví dụ |
|------|--------|
| Upload trên web | Mã form: `ds160_custom`, file: `DS160-mau.docx` |
| Copy thủ công | `backend/templates/forms/ds160_custom.docx` |

## Quy trình đầy đủ

1. **Upload giấy tờ** (passport, visa…) → menu **Upload**
2. AI trích xuất → **Review** → kiểm tra / sửa field
3. **Upload mẫu form** Word (file này) hoặc chọn mẫu có sẵn
4. Bấm **Tải Word** → file đã điền nằm trong `backend/exports/{id}/`

## Danh sách field thường dùng

- `identity.family_name`, `identity.given_names`, `identity.full_name`
- `identity.date_of_birth`, `identity.nationality`
- `passport.number`, `passport.expiry_date`
- `contact.address_line1`, `contact.city`, `contact.state`, `contact.postal_code`, `contact.country`
- `contact.address_from_date`, `contact.other_addresses_used`, `contact.other_addresses_history`
- `contact.phone_primary`, `contact.phone_secondary`, `contact.phone_work`
- `contact.other_phones_used`, `contact.other_phones_history`
- `contact.email`, `contact.other_emails_used`, `contact.other_emails_history`
- `immigration.sevis_id`, `immigration.visa_number`, `immigration.i94_number`
- `education.school_name`, `education.program_name`
