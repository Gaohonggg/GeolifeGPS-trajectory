# Tìm hiểu dữ liệu GPS thô và nguyên tắc tiền xử lý

## 1. GPS cho chúng ta biết điều gì?

Một điểm GPS là một phép đo vị trí tại một thời điểm. Một quỹ đạo (trajectory) là chuỗi các phép đo đó theo thời gian.

| Thành phần | Ý nghĩa | Đơn vị / lưu ý |
| --- | --- | --- |
| Latitude | Vĩ độ, vị trí theo hướng Bắc–Nam | Độ; phạm vi từ −90 đến 90 |
| Longitude | Kinh độ, vị trí theo hướng Đông–Tây | Độ; phạm vi từ −180 đến 180 |
| Timestamp | Thời điểm ghi nhận | Cần biết timezone của nguồn |
| Altitude | Độ cao | Đơn vị tùy nguồn; GeoLife dùng feet |
| User / trajectory ID | Người dùng và quỹ đạo tương ứng | Có thể lấy từ cấu trúc thư mục, tên file |

GPS là phép đo có sai số, không phải vị trí thật tuyệt đối. Khi thiết bị đứng yên, các điểm vẫn có thể dao động. Khi không có điểm được ghi lại, chúng ta không biết chắc người dùng đã di chuyển hay đứng yên.

Ngoài ra, tọa độ không tự cho biết ý nghĩa địa điểm. Phát hiện một khoảng dừng chưa đủ để kết luận đó là nhà, văn phòng hay quán ăn.

## 2. Hiểu định dạng GeoLife trước

Theo [User Guide 1.3, mục 4.1, trang 3](../Geolife_Trajectories/User%20Guide-1.3.pdf):

- Mỗi thư mục người dùng chứa các file quỹ đạo `.plt`.
- Mỗi file `.plt` chứa một quỹ đạo và được đặt tên theo thời điểm bắt đầu.
- Bỏ qua sáu dòng đầu; các dòng còn lại là các điểm GPS.
- Thời gian của điểm GPS và nhãn phương thức di chuyển được quy về GMT.

### 2.1. Bảy trường trong một dòng dữ liệu

| Vị trí | Trường | Cách hiểu |
| --- | --- | --- |
| 1 | Latitude | Vĩ độ, đơn vị độ thập phân |
| 2 | Longitude | Kinh độ, đơn vị độ thập phân |
| 3 | Giá trị cố định | Bằng `0` trong bộ dữ liệu này; không phải nhãn |
| 4 | Altitude | Độ cao theo feet; `−777` là giá trị không hợp lệ |
| 5 | Date dạng số | Số ngày, có phần thập phân, tính từ ngày 1899-12-30 |
| 6 | Date dạng chuỗi | Ngày ghi nhận |
| 7 | Time dạng chuỗi | Giờ ghi nhận |

### 2.2. Những giới hạn cần nhớ

- Tần suất ghi không đồng nhất. User Guide cho biết 91,5% quỹ đạo được ghi dày, ví dụ mỗi 1–5 giây hoặc 5–10 mét; đây không phải cam kết cho mọi file.
- Thời gian thu thập và số quỹ đạo giữa các người dùng khác nhau.
- Dữ liệu chủ yếu ở Bắc Kinh, nhưng cũng có ở các địa điểm khác. Không tự coi toàn bộ dữ liệu thuộc một thành phố hay timezone.
- Nhãn được mô tả là phương thức di chuyển của 73 người dùng. User Guide không mô tả nhãn chuẩn cho điểm dừng hoặc home/office.

Nguồn: [User Guide, mục 1, 2.1 và 4](../Geolife_Trajectories/User%20Guide-1.3.pdf).

## 3. Noise: nhiễu trong phép đo

### Hiện tượng

Một người đứng yên nhưng các điểm GPS tạo thành một đám mây nhỏ, hoặc quỹ đạo dao động quanh đường đi thực tế.

Sai số phụ thuộc môi trường và thiết bị. Nhà cao tầng có thể chắn tín hiệu; tín hiệu phản xạ từ công trình có thể gây multipath, tức tín hiệu đến máy thu qua nhiều đường truyền. Vì vậy không thể gán một mức sai số cố định cho mọi điểm. Xem [GPS.gov: GPS Accuracy](https://www.gps.gov/gps-accuracy).

### Ảnh hưởng đến phân tích

- Cộng khoảng cách giữa mọi điểm có thể tạo ra quãng đường dù người dùng đang đứng yên.
- Tốc độ tính giữa hai điểm có thể dao động mạnh, nhất là khi thời gian giữa chúng ngắn.
- Một lần dừng có thể bị tách thành nhiều đoạn nếu ngưỡng không gian quá nhỏ.

### Cách tiếp cận

1. Quan sát một số đoạn nghi ngờ đứng yên trên bản đồ và theo thời gian.
2. Xem mức phân tán không gian, tần suất ghi và các khoảng trống.
3. Đánh giá xem thuật toán phát hiện điểm dừng có thể chịu được độ dao động đó không.
4. Chỉ thêm bước làm mượt nếu có bằng chứng rằng nó cải thiện kết quả.

Moving average, median filter hoặc Kalman filter là các hướng có thể tìm hiểu sau. Mỗi cách có giả định và tham số riêng. Làm mượt có thể làm tròn góc rẽ, dịch vị trí hoặc làm mất một lần dừng ngắn; không mặc định áp dụng chỉ vì quỹ đạo nhìn đẹp hơn.

## 4. Outlier: điểm bất thường

### Phân biệt với noise

Noise thường biểu hiện qua sự dao động của phép đo. Outlier là điểm hoặc đoạn có hành vi khác thường so với ngữ cảnh. Hai khái niệm có thể chồng lấn; một điểm xa các điểm còn lại chưa đủ để kết luận là lỗi.

Ví dụ giả định: người dùng ở khu vực A lúc 08:00:00, xuất hiện cách đó 10 km sau 5 giây, rồi quay lại gần A sau 5 giây nữa. Đây là mẫu nhảy tọa độ đáng kiểm tra, chưa phải quy tắc xóa tự động.

### Các phép kiểm tra nên có

| Kiểm tra | Dấu hiệu | Hướng xử lý |
| --- | --- | --- |
| Phạm vi tọa độ | Vĩ độ / kinh độ ngoài phạm vi hợp lệ | Đánh dấu không hợp lệ và giữ lý do |
| Parse thời gian | Không đọc được ngày giờ | Tách vào nhóm lỗi; không đoán thời gian |
| Thứ tự thời gian | Thời gian giảm hoặc trùng | Kiểm tra dữ liệu gốc và chính sách sắp xếp |
| Nhảy vị trí | Khoảng cách lớn trong thời gian ngắn | Xem tốc độ và các điểm lân cận |
| Mẫu đi–về tức thời | Một điểm xa rồi quay lại | Kiểm tra điểm nghi ngờ cùng hai phía |
| Độ cao thiếu | Altitude bằng `−777` | Chuyển thành thiếu ở cột dẫn xuất; không loại cả điểm nếu chỉ dùng vị trí 2D |

Không coi `(0, 0)` là tọa độ sai về mặt toán học: đó là vị trí hợp lệ. Chỉ đánh dấu nghi ngờ khi có bằng chứng từ nguồn và ngữ cảnh.

### Dùng tốc độ để kiểm tra

Với hai điểm liên tiếp trong cùng đoạn:

- `delta_t = thời điểm sau − thời điểm trước`, đơn vị giây.
- `distance = khoảng cách địa lý giữa hai điểm`, đơn vị mét.
- `speed = distance / delta_t`, đơn vị m/s, chỉ tính khi `delta_t > 0`.
- Đổi từ m/s sang km/h bằng cách nhân `3.6`.

Đây là tốc độ trung bình suy ra giữa hai phép đo, không phải tốc độ tức thời đo trực tiếp. Khoảng cách thẳng giữa hai đầu cũng không biểu diễn đầy đủ đường đi thực tế.

Không đặt một ngưỡng tốc độ chung để xóa mọi trường hợp: GeoLife có nhiều phương thức di chuyển, kể cả tàu và máy bay. Ngưỡng phải gắn với mục tiêu, phân bố dữ liệu và kiểm tra thủ công.

## 5. Timezone: hiểu đúng thời điểm

### 5.1. Thời gian có và không có timezone

Chuỗi `2009-10-11 14:04:30` tự nó không cho biết đang dùng UTC hay giờ địa phương. Trong GeoLife, thông tin GMT đến từ User Guide. Với xử lý dữ liệu này, biểu diễn thời điểm đó dưới dạng UTC, ví dụ `2009-10-11T14:04:30Z`.

Một timestamp có thông tin timezone được gọi là timezone-aware. Timestamp không có thông tin đó là timezone-naive. Xem [Python datetime: aware và naive](https://docs.python.org/3/library/datetime.html#aware-and-naive-objects).

### 5.2. Gán timezone và chuyển timezone là hai việc khác nhau

- **Gán timezone:** xác định chuỗi nguồn đang biểu diễn thời gian theo múi giờ nào. Với chuỗi GeoLife, gán cách hiểu UTC.
- **Chuyển timezone:** biểu diễn cùng một thời điểm sang giờ của địa phương khác.

Ví dụ tại Bắc Kinh: `2009-10-11 14:04:30 UTC` tương ứng `2009-10-11 22:04:30 +08:00`. Không đọc chuỗi nguồn thành 14:04 giờ Bắc Kinh rồi mới chuyển sang UTC; thao tác đó làm sai thời điểm.

### 5.3. Nguyên tắc áp dụng

- Lưu timestamp chuẩn theo UTC; giữ giá trị nguồn để kiểm tra.
- Tính thời lượng và khoảng gián đoạn trên thời điểm UTC.
- Chỉ tạo giờ địa phương khi cần phân tích giờ trong ngày hoặc ngày trong tuần.
- Nếu dữ liệu trải nhiều vùng, cần chính sách xác định timezone; không áp `+08:00` cho tất cả quỹ đạo.
- Khi mở rộng sang nơi có giờ mùa hè, dùng timezone có tên và quy tắc lịch sử phù hợp, thay vì cộng một số giờ cố định.

## 6. Khoảng cách, đơn vị và hệ tọa độ

Latitude/longitude có đơn vị độ. Không tính Euclidean trực tiếp trên hai cột này rồi hiểu kết quả là mét. Độ dài tương ứng với một độ kinh độ thay đổi theo vĩ độ.

Hai hướng tính khoảng cách:

| Hướng | Cách hiểu | Lưu ý |
| --- | --- | --- |
| Khoảng cách trên bề mặt Trái Đất | Haversine dùng mô hình cầu; geodesic có thể dùng mô hình ellipsoid | Kiểm tra thứ tự tọa độ, độ/radian và đơn vị đầu ra |
| Khoảng cách phẳng | Chuyển sang hệ tọa độ chiếu phù hợp rồi tính theo x/y | Chọn phép chiếu theo khu vực và độ chính xác cần thiết |

Tài liệu [PostGIS ST_Distance](https://postgis.net/docs/ST_Distance.html) minh họa sự khác nhau giữa khoảng cách phẳng theo đơn vị hệ tọa độ và khoảng cách địa lý theo mét.

Một lỗi thường gặp khác là đảo latitude/longitude. GeoLife lưu latitude trước longitude, còn GeoJSON dùng longitude trước latitude theo [RFC 7946, mục 3.1.1](https://datatracker.ietf.org/doc/html/rfc7946#section-3.1.1). Luôn kiểm tra quy ước của thư viện và định dạng xuất.

Nếu đưa altitude về mét, dùng `altitude_m = altitude_ft × 0.3048`, sau khi xử lý giá trị thiếu. Không giả định cột altitude có sẵn đơn vị mét.

## 7. Khoảng trống, điểm trùng và tần suất ghi

### 7.1. Khoảng trống thời gian

Hai điểm gần nhau về không gian nhưng cách nhau một giờ không chứng minh người dùng đã ở đó suốt một giờ. Có thể họ rời đi rồi quay lại hoặc thiết bị ngừng ghi.

Tính phân bố `delta_t` trước khi chọn ngưỡng tách đoạn. Khi khoảng trống vượt ngưỡng, đánh dấu hoặc tạo segment mới. Không nội suy qua khoảng trống dài để tạo bằng chứng cho một lần dừng.

Giữ ranh giới file nguồn khi khám phá ban đầu. Nếu nối các file cùng người dùng, cần chính sách rõ về thứ tự, phần chồng lấn và khoảng gián đoạn; không nối chỉ vì cùng user ID.

### 7.2. Điểm trùng

- Trùng hoàn toàn người dùng, thời gian và tọa độ: có thể là bản ghi lặp; cần chính sách loại trùng.
- Cùng tọa độ nhưng khác thời gian: có thể là bằng chứng đứng yên, cần giữ.
- Cùng thời gian nhưng khác tọa độ: là xung đột cần kiểm tra; không chia khoảng cách cho thời gian bằng 0.

### 7.3. Tần suất ghi không đều

Một thiết bị ghi mỗi giây sẽ tạo nhiều điểm hơn thiết bị ghi mỗi phút, dù cả hai ở một địa điểm trong cùng thời lượng. Vì vậy, số điểm không thay thế cho thời gian lưu lại.

Resampling là đưa dữ liệu về lưới thời gian chung; interpolation là ước lượng điểm chưa quan sát. Đây là các lựa chọn có thể cần sau này, không phải bước bắt buộc. Nếu thực hiện, đánh dấu điểm tổng hợp và không coi chúng là phép đo GPS thật.

## 8. Quy trình tiền xử lý đề xuất


## 9. Nguyên tắc để kết quả đáng tin cậy

- **Giữ nguyên dữ liệu gốc:** có thể truy ngược mỗi điểm đã xử lý về người dùng, file và dòng nguồn.
- **Ưu tiên đánh dấu trước khi xóa:** lưu nguyên nhân và quyết định xử lý, phân biệt lỗi chắc chắn với nghi ngờ.
- **Không đoán thông tin thiếu:** thiếu độ cao không có nghĩa là độ cao bằng 0; thiếu quan sát không có nghĩa là đứng yên.
- **Ngưỡng phải có lý do:** ghi đơn vị, nguồn lựa chọn, phiên bản cấu hình và ảnh hưởng khi thay đổi.
- **Đánh giá theo nhiều trường hợp:** đoạn ghi dày/thưa, nhiều/ít nhiễu, di chuyển/dừng, có/không có khoảng trống.
- **Không chỉ tối ưu hình thức:** quỹ đạo mượt hơn chưa chắc phản ánh hành vi đúng hơn.
- **Tách quan sát và suy luận:** điểm GPS là phép đo; điểm dừng là kết quả thuật toán; tên loại địa điểm là một lớp suy luận khác.
- **Bảo vệ dữ liệu vị trí:** khi chia sẻ hình minh họa, cân nhắc giảm độ chi tiết vì quỹ đạo có thể tiết lộ nơi thường xuyên xuất hiện.

Nếu sau này huấn luyện mô hình, cần tránh chia ngẫu nhiên các điểm sát nhau giữa train/test. Cách chia theo người dùng hoặc thời gian phải phù hợp với tình huống đánh giá dự kiến để hạn chế rò rỉ dữ liệu.

## 10. Kiểm tra chất lượng và liên hệ với điểm dừng

Một báo cáo tiền xử lý tối thiểu nên có:

| Nội dung | Cần quan sát |
| --- | --- |
| Quy mô | Số người dùng, file, segment và điểm trước/sau |
| Dữ liệu lỗi | Số bản ghi lỗi theo từng nguyên nhân |
| Thời gian | Phân bố delta thời gian, điểm trùng timestamp, khoảng trống |
| Chuyển động | Phân bố khoảng cách và tốc độ, các đoạn đáng nghi |
| Tác động của lọc | Tỷ lệ loại theo người dùng/file; ví dụ trước/sau |
| Khả năng tái lập | Quy tắc xử lý, tham số và phiên bản dữ liệu |

Đối với phát hiện điểm dừng, hai ý tưởng cơ bản là phạm vi không gian đủ nhỏ và thời gian lưu lại đủ dài. Tuy nhiên, ngưỡng nhỏ quá có thể tách một lần dừng do nhiễu; ngưỡng lớn quá có thể gộp các địa điểm khác nhau. Khoảng mất tín hiệu có thể làm thời lượng bị suy diễn quá mức nếu xử lý không đúng.

Đầu ra dự kiến có thể gồm vị trí đại diện, thời điểm bắt đầu/kết thúc, thời lượng quan sát và các cờ chất lượng. Cần định nghĩa rõ cách tính thời lượng, cách xử lý khoảng trống và cách chọn vị trí đại diện. Nếu có confidence, đó phải là chỉ số được định nghĩa và kiểm chứng; không mặc nhiên là xác suất kết quả đúng.


## Tài liệu tham khảo

1. [GeoLife User Guide 1.3](../Geolife_Trajectories/User%20Guide-1.3.pdf): mô tả dữ liệu, tần suất ghi, định dạng PLT, GMT và nhãn phương thức di chuyển.
2. [GPS.gov — GPS Accuracy](https://www.gps.gov/gps-accuracy): yếu tố ảnh hưởng độ chính xác và multipath.
3. [Python datetime — Aware and naive objects](https://docs.python.org/3/library/datetime.html#aware-and-naive-objects): cách hiểu thời gian có/không có timezone.
4. [PostGIS — ST_Distance](https://postgis.net/docs/ST_Distance.html): đơn vị và cách tính khoảng cách phẳng/địa lý.
5. [RFC 7946 — GeoJSON, mục 3.1.1](https://datatracker.ietf.org/doc/html/rfc7946#section-3.1.1): thứ tự longitude/latitude trong GeoJSON.
