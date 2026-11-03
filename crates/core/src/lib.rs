//! Architecture-independent, bounded tensor artifacts and region replacement.
pub mod artifact;
pub mod tensor;
pub use artifact::*;
pub use tensor::*;

pub mod disk_tensor;
pub use disk_tensor::*;
