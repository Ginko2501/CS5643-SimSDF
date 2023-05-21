from util import *
from shape import *

MULTIPLIER = 10


@ti.dataclass
class Collision:
    p1: vec2        # contact point on object 1
    r1: vec2
    r2: vec2
    n1: vec2
    i1: ti.i32
    i2: ti.i32
    sep: ti.f64
    nc: ti.i32
    gamma: ti.f64
    v_n: ti.f64

# TODO: you can add other data class if you find that helpful for your
# implementation. (e.g. BoxState in scene_state.py)

# Contact Solver


@ti.data_oriented
class CollisionSolver:
    
    def __init__(self, scene_state, Cr, β, μ):
        self.scene = scene_state
        self.Cr = Cr
        self.β = β
        self.μ = μ
        self.scene.objs = self.scene.spheres
        self.init_contact()

    # TODO: Initialize the other fields you need for implementing collision response
    def init_contact(self):
        self.nc = ti.field(shape=(), dtype=ti.i32)
        # Initialize other variables you need below:
        # you can initialize them in the form of self.xx = ti.field(xxx)
        self.N = self.scene.num_sphere[None]
        self.collisions = Collision.field(shape=(self.N*self.N+MULTIPLIER*self.N,))
        self.nc[None] = 0
        self.gamma_x = ti.Vector.field(2, shape=(self.N,), dtype=ti.f64)
        self.sum_w = ti.field(shape=(self.N,), dtype=ti.f64)
        self.limitExceeded = ti.field(shape=(), dtype=ti.f64)

    # clear all of your contacts
    # This function is called before the collision detection procerss.
    @ti.func
    def clearContact(self):
        self.nc[None] = 0
        self.sum_w.fill(0)
        self.gamma_x.fill(vec2(0))
        # you can clear other attributes below if you need to do so
                    
    @ti.kernel 
    def collision_detection(self):
        for i in range(self.scene.num_sphere[None]):
            for j in range(i + 1, self.scene.num_sphere[None]):
                itx = self.scene.spheres[i].collision_detection(self.scene.spheres[j])
                if itx[0] != -1 and itx[1] != -1:
                    self.scene.collide[self.scene.num_collide[None]] = itx
                    ti.atomic_add(self.scene.num_collide[None], 1)
                    
                    r1 = itx - self.scene.spheres[i].o
                    r2 = itx - self.scene.spheres[j].o
                    n = (self.scene.spheres[j].o -self.scene.spheres[i].o).normalized()
                    self.addContact(itx, r1, r2, n, i, j, 0, 1)

    # TODO: Implement this function that is going be triggered whenever a collision is being detected
    @ti.func
    def addContact(self, p1: vec2, r1: vec2, r2: vec2, n1: vec2, i1: int, i2: int, sep: float, nc: int):
        """
        This function is being triggered after the
        :param p1: vec2, the mass center of the reference rigid body
        :param r1: vec2, the displacement from the reference rigid body mass center to the contact point
        :param r2: vec2, the displacement from the incident rigid body mass center to the contact point
        :param n1: vec2, the normal of the reference edge
        :param i1: int, the index of the reference rigid body. You may find info related to this rigid body in self.state.boxes[i1]
        :param i2: int, the index of the incident rigid body. You may find info related to this rigid body in self.state.boxes[i2]
        :param sep: float, the maximum seperation distance between two boxes
        :param nc: int, number of contact points in between body i1 and i2.
        :return: void
        """
        # Note that if i1 < 0, the reference rigid body could be a rigid line boundary. Then, p1 would be a point on the
        # line boundary, r1 would be vec2(0, 0) and n1 would be the normal of the line boundary

        # compute the relative velocity
        v = vec2(0.0)

        if i1 >= 0:
            v += self.scene.objs[i1].v + crossZ(self.scene.objs[i1].ω, r1)
        if i2 >= 0:
            v -= self.scene.objs[i2].v + crossZ(self.scene.objs[i2].ω, r2)

        # compute the relative normal velocity
        v_n = n1.dot(v)
        self.collisions[ti.atomic_add(self.nc[None], 1)] = Collision(p1, r1, r2, n1, i1, i2, sep, nc, 0., v_n)

    @ti.func
    def initSums(self):
        # Compute sum of impulses affecting each object
        self.gamma_x.fill(vec2(0., 0.))
        self.sum_w.fill(0)

        ti.loop_config(serialize=True)
        for k in range(self.nc[None]):
            collision = self.collisions[k]
            if collision.i1 >= 0:
                d_va = collision.gamma * collision.n1
                d_wa = collision.r1.cross(d_va)
                ti.atomic_add(self.gamma_x[collision.i1], d_va)
                ti.atomic_add(self.sum_w[collision.i1], d_wa)
            if collision.i2 >= 0:
                d_vb = -collision.gamma * collision.n1
                d_wb = collision.r2.cross(d_vb)
                ti.atomic_add(self.gamma_x[collision.i2], d_vb)
                ti.atomic_add(self.sum_w[collision.i2], d_wb)

        for i in range(self.N):
            self.gamma_x[i] /= self.scene.objs[i].m
            self.sum_w[i] /= self.scene.objs[i].I

    # TODO: implemnt your projected Gauss-Seidel Contact solver below
    @ti.kernel
    def PGS(self):
        # if self.nc[None] == 0:
        #     return

        self.initSums()
        self.limitExceeded[None] = 4000

        ti.loop_config(serialize=True)
        while (self.limitExceeded[None] > 1e-8):
            # for i in range (40):
            self.limitExceeded[None] = 0
            # if(self.limitExceeded[None] != 0):
            # print("limit_efdsalfjdsxceeded", self.limitExceeded[None])
            # self.initSums()
            # ti.loop_config(serialize=True)
            for k in range(self.nc[None]):
                # self.initSums()
                C = self.collisions[k]
                i, j, n = C.i1, C.i2, C.n1
                m1_i, m2_i, I1_i, I2_i = 0.0, 0.0, 0.0, 0.0
                sum_va, sum_vb = vec2(0.0), vec2(0.0)
                sum_wa, sum_wb = 0.0, 0.0

                if i >= 0:
                    m1_i = 1./self.scene.objs[i].m
                    I1_i = 1./self.scene.objs[i].I
                    sum_va = self.gamma_x[i]
                    sum_wa = self.sum_w[i]

                if j >= 0:
                    m2_i = 1./self.scene.objs[j].m
                    I2_i = 1./self.scene.objs[j].I
                    sum_vb = self.gamma_x[j]
                    sum_wb = self.sum_w[j]

                d_va = C.gamma * m1_i * n
                d_wa = I1_i*C.gamma*C.r1.cross(n)

                d_vb = -C.gamma * m2_i * n
                d_wb = -I2_i*C.gamma*C.r2.cross(n)

                other_v = (sum_va - d_va) - (sum_vb - d_vb)
                other_wa = sum_wa - d_wa
                other_wb = sum_wb - d_wb

                cross_a = crossZ(other_wa, C.r1)
                cross_b = crossZ(other_wb, C.r2)

                sum = other_v + cross_a - cross_b

                meff1 = m1_i + m2_i + I1_i * n.dot(crossZ(C.r1.cross(n), C.r1)) + I2_i * n.dot(crossZ(C.r2.cross(n), C.r2))
                meff = 1./meff1

                gamma_new = -meff * (n.dot(sum) + self.β * ti.min(0., C.sep) + (1 + self.Cr) * -C.v_n)
                gamma_new = ti.max(0.0, gamma_new)

                Δɣ = gamma_new - self.collisions[k].gamma

                ti.atomic_add(self.limitExceeded[None],  ti.abs(Δɣ))

                if i >= 0:
                    ti.atomic_add(self.gamma_x[i], Δɣ * n * m1_i)
                    ti.atomic_add(self.sum_w[i], Δɣ * I1_i * C.r1.cross(n))
                if j >= 0:
                    ti.atomic_add(self.gamma_x[j], -Δɣ * n * m2_i)
                    ti.atomic_add(self.sum_w[j], -Δɣ * I2_i * C.r2.cross(n))

                self.collisions[k].gamma = gamma_new

    # TODO: update the velocities stored in self.state.boxes based on the impulses you solved for

    @ti.kernel
    def apply_impulses(self):
        for k in range(self.nc[None]):
            C = self.collisions[k]
            i, j, n = C.i1, C.i2, C.n1
            if i >= 0:
                ti.atomic_add(self.scene.spheres[i].v, -C.gamma * n / self.scene.spheres[i].m)
                self.scene.spheres[i].ω -= C.gamma * C.r1.cross(n) / self.scene.spheres[i].I
            if j >= 0:
                ti.atomic_add(self.scene.spheres[j].v, C.gamma * n / self.scene.spheres[j].m)
                self.scene.spheres[j].ω += C.gamma * C.r2.cross(n) / self.scene.spheres[j].I
