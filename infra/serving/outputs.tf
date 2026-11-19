output "url" { value = "http://${aws_lb.api.dns_name}" }
output "image" { value = local.image }
output "slots" {
  value = {
    for slot, v in local.slot_versions : slot => {
      model_version = v
      weight        = local.weights[slot]
      live          = slot == var.live_slot
    }
  }
}
