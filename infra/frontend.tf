# ════════════════════════════════════════════════════════════
#  프론트(Next.js 정적 export) 서빙 보조
#
#  문제: S3 + OAC 조합에서 CloudFront 는 루트(default_root_object)에만
#        index.html 을 붙여준다. /schedule/ 같은 하위 경로는 그대로 S3 키를
#        찾으므로 404 가 난다.
#  해결: 뷰어 요청 시점에 URI 를 다시 쓴다.
#        /schedule/  → /schedule/index.html
#        /schedule   → /schedule/index.html
# ════════════════════════════════════════════════════════════

resource "aws_cloudfront_function" "spa_rewrite" {
  name    = "${var.prefix}-index-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Append index.html for directory-style paths"
  publish = true

  code = <<-EOT
    function handler(event) {
      var request = event.request;
      var uri = request.uri;

      // 확장자가 있으면 정적 자산 → 그대로 통과 (.js, .css, .avif, .svg ...)
      if (uri.includes('.')) {
        return request;
      }
      // 디렉터리 경로 → index.html 부착
      if (uri.endsWith('/')) {
        request.uri = uri + 'index.html';
      } else {
        request.uri = uri + '/index.html';
      }
      return request;
    }
  EOT
}

output "cloudfront_function_arn" {
  description = "api.tf 의 default_cache_behavior 에 연결할 함수 ARN"
  value       = aws_cloudfront_function.spa_rewrite.arn
}
