// Docker Bake — one Dockerfile, three jobs: `docker buildx bake <target>`.
// build = server runtime venv · ci = lint/type/test toolchain · serve = bare runtime.
// One image name (claudeplans), stage as the tag.

group "default" {
  targets = ["serve"]
}

target "build" {
  dockerfile = "Dockerfile"
  target     = "build"
  tags       = ["claudeplans:build"]
}

target "ci" {
  dockerfile = "Dockerfile"
  target     = "ci"
  tags       = ["claudeplans:ci"]
}

target "serve" {
  dockerfile = "Dockerfile"
  target     = "serve"
  tags       = ["claudeplans:serve"]
}
